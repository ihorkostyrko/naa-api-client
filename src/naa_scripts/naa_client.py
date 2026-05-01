"""
NAA Scripts
Direct interaction with Nasuni Access Anywhere (formerly StorageMadeEasy) API.

Author: Ihor Kostyrko
Github: https://github.com/ihorkostyrko/naa-api-client
License: MIT
Copyright (c) 2026 Ihor Kostyrko
"""

import base64
import os
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class NAAApiError(Exception):
    """Raised when the NAA API returns a non-ok status."""

    def __init__(self, function: str, status: str, statusmessage: str) -> None:
        super().__init__(f"{function} failed: '{status}' - {statusmessage}")
        self.status = status
        self.statusmessage = statusmessage


class NAAClient:
    """Client for interacting with the NAA API."""

    def __init__(self, api_host: str, username: str, password: str) -> None:
        self.api_host = api_host
        self.token = self._get_token(username, password)

    def _request(self, function: str, params: dict, token: str = None) -> dict:
        """Send a POST request to /api/rpc.php and return the full parsed JSON dict.

        The returned dict contains top-level keys such as 'status', 'statusmessage'.

        Raises:
            NAAApiError:  If the API returns a non-ok status with a statusmessage.
            RuntimeError: If the API returns a non-ok status without a statusmessage,
                          or if the response is not valid JSON.
        """
        _token = token if token is not None else self.token
        body = {"token": _token, "function": function, "apiformat": "json"}
        body.update(params)
        url = f"{self.api_host}/api/rpc.php"

        # The getToken function is usually very fast (less than 1 second)
        # But some other functions (e.g. getFolderContents) may take much longer.
        request_timeout = 30 if function.lower() == "gettoken" else 120
        response = requests.post(url, data=body, verify=False, timeout=request_timeout)
        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as e:
            raise RuntimeError(
                f"{function} failed: Invalid JSON response: {response.text}"
            ) from e

        if data.get("status") != "ok":
            if "statusmessage" in data:
                raise NAAApiError(function, data["status"], data["statusmessage"])
            else:
                raise RuntimeError(
                    f"{function} failed. Response: {data}. Raw response: {response.text}."
                )
        return data

    def _get_token(self, username: str, password: str) -> str:
        """Authenticate and return a session token."""
        data = self._request(
            "gettoken", {"us_login": username, "us_pwd": password}, token="*"
        )
        return data["token"]

    def get_folder_contents(self, folder_id: int = 0) -> list:
        """Return the list of items in the specified folder (default: root)."""
        data = self._request(
            "getFolderContents",
            {
                "fi_pid": folder_id,
                "from": 0,
                "count": 0,
                "fi_type": "",
                "showpath": "y",
            },
        )
        filelist = data["filelist"]

        # filelist may be a dict when there is only one item
        if isinstance(filelist, dict):
            filelist = [filelist]
        return filelist

    def check_path_exists(self, path: str, pid: int = 0) -> dict:
        """Check whether a file or folder at the given path exists."""
        data = self._request(
            "checkPathExists", {"path": path, "pid": pid, "options": ""}
        )
        return data

    def refresh_folder(
        self, folder_id: int = 0, poll_interval: float = 2.0, timelimit: float = 600.0
    ) -> bool:
        """Trigger a background cloud refresh for a folder and wait until it completes.

        Sends getFolderContents with refresh='y' and refreshtype='a' to start an
        asynchronous background refresh. Then polls using the returned refreshtoken
        until the refresh is complete.

        Args:
            folder_id:     The folder ID to refresh. 0 for the root folder.
            poll_interval: Seconds to wait between polling requests.
            timelimit:     Maximum seconds to wait before raising TimeoutError.

        Returns:
            True when the folder refresh has completed successfully.

        Raises:
            RuntimeError:  If the API reports an error or the refresh fails.
            TimeoutError:  If the refresh does not complete within `timelimit` seconds.
        """

        # We only need to get the refresh token
        # So we can limit the count to 1 and get only `basic_fields` to reduce response size
        request_data = {
            "fi_pid": folder_id,
            "from": 0,
            "count": 1,
            "fi_type": "",
            "showpath": "y",
            "refresh": "y",
            "refreshtype": "a",
            "options": "basic_fields",
        }

        # Step 1: keep calling getFolderContents with refresh='y' + refreshtype='a'
        # until the server issues a background refresh token.
        deadline = time.monotonic() + timelimit
        refresh_token = ""
        while not refresh_token:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Folder refresh did not start within {timelimit}s "
                    f"(folder_id={folder_id})"
                )

            data = self._request("getFolderContents", request_data)

            # The response may include a refresh token if the refresh will be done asynchronously in the background.
            # If refresh_token is not present, then the folder was not refreshed. Most probably it was
            # refreshed recently
            refresh_token = (data.get("refreshresult") or {}).get("token", "")
            if not refresh_token:
                time.sleep(poll_interval)

        # Step 2: poll until the background refresh completes
        request_data["refreshtoken"] = refresh_token
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Folder refresh did not complete within {timelimit}s "
                    f"(folder_id={folder_id}, refreshtoken={refresh_token})"
                )

            time.sleep(poll_interval)

            data = self._request("getFolderContents", request_data)

            if data.get("stillsyncing"):
                continue

            return True

    def upload_file(self, file_path: str, folder_id: int, timeout: int = 300) -> dict:
        """Upload a file in 3 steps: doInitUpload -> uploader1.cgi -> doCompleteUpload.

        Args:
            file_path:  Absolute or relative path to the local file to upload.
            folder_id:  Destination folder ID (fi_pid). 0 for the root folder.
            timeout:    Socket timeout in seconds for the upload request (default: 300).
                        This is a per-read/write socket timeout, not a total time limit.

        Returns:
            A dict with the following keys:
              fi_id      — fi_id of the newly created file record.
              md5        — MD5 hex digest of the uploaded bytes (empty if not computed).
              file_info  — Full file metadata record from doCompleteUpload response.

        Raises:
            RuntimeError: If any step fails or expected fields are missing.
        """
        filename = os.path.basename(file_path)
        filesize = os.path.getsize(file_path)

        # Step 1: initialize upload session and get uploadcode.
        init_result = self._request(
            "doInitUpload",
            {
                "fi_name": filename,
                "fi_filename": filename,
                "fi_pid": folder_id,
                "fi_size": filesize,
                "responsetype": "json",
            },
        )
        uploadcode = init_result.get("uploadcode")
        if not uploadcode:
            raise RuntimeError(
                f"upload_file failed: Missing 'uploadcode' in doInitUpload response: {init_result}"
            )

        # Step 2: upload file bytes to uploader1.cgi using the uploadcode token.
        upload_url = f"{self.api_host}/cgi-bin/uploader/uploader1.cgi?{uploadcode}"
        with open(file_path, "rb") as f:
            upload_response = requests.post(
                upload_url,
                files={"datafile": (filename, f, "application/octet-stream")},
                verify=False,
                timeout=timeout,
            )
        upload_response.raise_for_status()

        try:
            upload_data = upload_response.json()
        except ValueError as e:
            raise RuntimeError(
                f"upload_file failed: Invalid JSON from uploader1.cgi: {upload_response.text}"
            ) from e

        if upload_data.get("success") != "y":
            raise RuntimeError(
                f"upload_file failed in uploader1.cgi: {upload_data.get('error', 'Unknown error')}"
            )

        # Step 3: finalize upload and create/update file DB record.
        data = self._request(
            "doCompleteUpload",
            {
                "uploadcode": uploadcode,
                "fi_size": filesize,
            },
        )

        # Validate response structure and content
        if "file" not in data:
            raise RuntimeError(
                f"upload_file failed: Missing 'file' in doCompleteUpload response: {data}"
            )

        if "fi_id" not in data["file"]:
            raise RuntimeError(
                f"upload_file failed: Missing 'fi_id' in doCompleteUpload.file: {data}"
            )

        fi_id = data["file"]["fi_id"]
        if not fi_id:
            raise RuntimeError(
                f"upload_file failed: Invalid 'fi_id' in doCompleteUpload.file: {data}"
            )

        return {
            "fi_id": fi_id,
            "md5": upload_data.get("md5", ""),
            "file_info": data["file"],
        }

    def rename_file(
        self,
        fi_id: int,
        new_name: str,
        fi_description: str | None = None,
        fi_tags: str | None = None,
        overwrite: bool = False,
    ) -> dict:
        """Rename a file.

        Args:
            fi_id:     ID of the file to rename.
            new_name:  New display name for the file.
            fi_description: Optional new description for the file. If None, the description will not be changed. If empty string then remove existing description.
            fi_tags: Optional new tags for the file. If None, the tags will not be changed. If empty string then remove existing tags.
            overwrite: If True, overwrite an existing file with the new name. If False, the rename will fail if another file with the new name already exists in the same folder.

        Returns:
            The updated file metadata record from the response.

        Raises:
            NAAApiError:  If the API returns an error.
            RuntimeError: If the expected 'file' key is missing from the response.
        """
        overwrite_str = "y" if overwrite else "n"
        data = self._request(
            "doRenameFile",
            {
                "fi_id": fi_id,
                "fi_name": new_name,
                "fi_description": fi_description,
                "fi_tags": fi_tags,
                "overwrite": overwrite_str,
            },
        )

        if "file" not in data:
            raise RuntimeError(
                f"rename_file failed: Missing 'file' in response: {data}"
            )

        return data["file"]

    def download_file(self, fi_id: int, dest_path: str, timeout: int = 300) -> str:
        """Download a file by its fi_id and save it to dest_path.

        Args:
            fi_id:      ID of the file to download.
            dest_path:  Full local path (including filename) to save the file to.
            timeout:    Socket timeout in seconds (default: 300).

        Returns:
            The path where the file was saved.

        Raises:
            RuntimeError: If the server returns an error, or the download is incomplete.
        """
        url = f"{self.api_host}/api/rpc.php"
        params = {"token": self.token, "function": "getfile", "fi_id": fi_id}
        response = requests.get(
            url, params=params, verify=False, timeout=timeout, stream=True
        )

        # On failure the server sets X-NAA-DOWNLOAD-ERROR (Base64-encoded message)
        # and X-NAA-DOWNLOAD-ERROR-STATUS, plus optional provider-level headers.
        # X-SME-* headers are legacy aliases carrying the same values.
        error_header = response.headers.get("X-NAA-DOWNLOAD-ERROR", "")
        error_status = response.headers.get("X-NAA-DOWNLOAD-ERROR-STATUS", "")
        provider_error = response.headers.get("X-PROVIDER-DOWNLOAD-ERROR", "")
        provider_error_code = response.headers.get("X-PROVIDER-DOWNLOAD-ERROR-CODE", "")

        if not response.ok or error_header:
            parts = []
            if error_header:
                try:
                    parts.append(
                        base64.b64decode(error_header).decode("utf-8", errors="replace")
                    )
                except Exception:
                    parts.append(error_header)
            if error_status:
                parts.append(f"error_status={error_status}")
            if provider_error:
                try:
                    parts.append(
                        "provider: "
                        + base64.b64decode(provider_error).decode(
                            "utf-8", errors="replace"
                        )
                    )
                except Exception:
                    parts.append(f"provider: {provider_error}")
            if provider_error_code:
                parts.append(f"provider_code={provider_error_code}")
            if not parts:
                # No header detail available — surface the HTTP status.
                response.raise_for_status()
            raise RuntimeError(
                f"download_file failed (HTTP {response.status_code}): {'; '.join(parts)}"
            )

        expected_length = response.headers.get("Content-Length")
        bytes_written = 0
        with open(dest_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                f.write(chunk)
                bytes_written += len(chunk)

        # If an error occurs after the server has already started streaming, no error
        # headers can be sent. Detect a truncated download via Content-Length mismatch.
        if expected_length is not None and bytes_written != int(expected_length):
            raise RuntimeError(
                f"download_file failed: incomplete download for fi_id={fi_id} "
                f"(expected {expected_length} bytes, got {bytes_written})"
            )

        return dest_path

    def get_file_url(
        self,
        fi_id: int,
        password: str = "",
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
    ) -> str:
        """Generate a shareable link for a file.

        Args:
            fi_id:     ID of the file to share.
            password:  Password to protect the link (empty = no password).
            days:      Expiry in days (0 = permanent if hours and minutes are also 0).
            hours:     Expiry hours component.
            minutes:   Expiry minutes component.

        Returns:
            The generated shareable URL string.

        Raises:
            RuntimeError: If the API returns an error.
        """
        data = self._request(
            "getFileURL",
            {
                "fi_id": fi_id,
                "password": password,
                "days": days,
                "hours": hours,
                "minutes": minutes,
            },
        )

        if "url" not in data:
            raise RuntimeError(
                f"get_file_url failed: Missing 'url' in response: {data}"
            )

        return data["url"]

    def create_folder(self, name: str, parent_id: int) -> dict:
        """Create a new folder inside parent_id.

        Args:
            name:      Display name for the new folder.
            parent_id: fi_id of the parent folder.

        Returns:
            The folder metadata record from the response.

        Raises:
            RuntimeError: If the API returns an error.
        """
        data = self._request(
            "doCreateNewFolder",
            {
                "fi_name": name,
                "fi_pid": parent_id,
            },
        )

        if "file" not in data:
            raise RuntimeError(
                f"create_folder failed: Missing 'file' in response: {data}"
            )

        return data["file"]

    def copy_file(self, fi_id: int, dest_folder_id: int) -> dict:
        """Copy a file into the destination folder.

        Args:
            fi_id:          ID of the file to copy.
            dest_folder_id: fi_id of the destination folder.

        Returns:
            The full API response dict (may contain backgroundtaskid).

        Raises:
            RuntimeError: If the API returns an error.
        """
        data = self._request(
            "doCopyFile",
            {
                "fi_id": fi_id,
                "fi_pid": dest_folder_id,
            },
        )
        return data

    def move_folder(self, fi_id: int, dest_folder_id: int) -> dict:
        """Move a folder to a new parent folder.

        Args:
            fi_id:          ID of the folder to move.
            dest_folder_id: fi_id of the destination parent folder.

        Returns:
            The full API response dict (may contain backgroundtaskid).

        Raises:
            RuntimeError: If the API returns an error.
        """
        data = self._request(
            "doMoveFolder",
            {
                "fi_ids": fi_id,
                "dir_id": dest_folder_id,
            },
        )
        return data

    def delete_folder(self, fi_id: int) -> dict:
        """Delete a folder and all of its contents.

        Args:
            fi_id: ID of the folder to delete.

        Returns:
            The full API response dict (may contain backgroundtaskid).

        Raises:
            RuntimeError: If the API returns an error.
        """
        data = self._request(
            "doDeleteFolder",
            {
                "fi_id": fi_id,
            },
        )
        return data

    def delete_file(self, fi_id: int) -> dict:
        """Delete a file by its fi_id.

        Args:
            fi_id: ID of the file to delete.

        Returns:
            The full API response dict (response.backgroundtask is 0 when synchronous).

        Raises:
            NAAApiError: If the API returns an error.
        """
        data = self._request(
            "doDeleteFile",
            {
                "fi_id": fi_id,
            },
        )
        return data

    def await_all_tasks_completion(
        self,
        task_type: str | None = None,
        poll_interval: float = 2.0,
        timelimit: float = 3600.0,
    ) -> None:
        """Poll getUserBackgroundTasks until no active tasks of the specified type remain.

        Active tasks are those with status 'a' (queued), 'w' (running), or 'p' (paused).

        task_type accepts two kinds of values:

          bt_type values (server-side filter, exact match on bt_type / bt_subtype):
            'sync'   — provider sync tasks
            'email'  — email backup tasks
            'custom' — all modern tasks (copy, move, delete, refresh, etc.)

          Callback names (client-side filter on the 'callback' response field;
          these are all bt_type='custom' tasks differentiated by bt_data.callback):
            'CopyFolder'         — folder copy
            'CopyFiles'          — file copy
            'MoveFiles'          — file/folder move
            'MoveFolder'         — folder move
            'DeleteFileObjects'  — file or folder deletion
            'FolderRefresh'      — cloud folder refresh
            'InitialSync'        — provider initial sync
            'ReSync'             — provider re-sync
            'TrashArchive'       — trash archiving
            (and others stored in bt_data.callback)

        Args:
            task_type:     Optional task type to wait for. When None (default), waits
                           for ALL active tasks regardless of type.
            poll_interval: Seconds to wait between each poll (default: 2).
            timelimit:     Maximum total seconds to wait before raising
                           TimeoutError (default: 3600).

        Raises:
            TimeoutError: If active tasks do not finish within `timelimit` seconds.
        """
        _BT_TYPES = frozenset({"sync", "email", "custom"})

        # Determine whether task_type is a bt_type (server-side filter) or a
        # callback name (custom task — requires client-side filtering).
        typefilter = ""
        callback_filter = ""
        if task_type:
            if task_type in _BT_TYPES:
                typefilter = task_type
            else:
                typefilter = "custom"
                callback_filter = task_type.lower()

        deadline = time.monotonic() + timelimit
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Background tasks did not complete within {timelimit}s"
                )

            params: dict = {"statusfilter": "a,w,p"}
            if typefilter:
                params["typefilter"] = typefilter

            if not callback_filter:
                # Fast path: server total is sufficient.
                params["limit"] = 1
                data = self._request("getUserBackgroundTasks", params)
                total = data.get("response", {}).get("total", 0)
                if int(total) == 0:
                    return
            else:
                # Fetch all matching tasks and filter client-side by callback name.
                params["limit"] = 1000
                data = self._request("getUserBackgroundTasks", params)
                tasks = data.get("response", {}).get("tasks", [])
                if isinstance(tasks, dict):
                    tasks = [tasks]
                if not any(
                    t.get("callback", "").lower() == callback_filter for t in tasks
                ):
                    return

            time.sleep(poll_interval)

    def await_task_completion(
        self, bt_id: int, poll_interval: float = 2.0, timelimit: float = 3600.0
    ) -> dict:
        """Poll getUserBackgroundTasks until the given task reaches a terminal state.

        Terminal states: 'completed', 'error', 'canceled', 'cancelled'.

        Args:
            bt_id:         Background task ID returned by a previous API call.
            poll_interval: Seconds to wait between each poll (default: 2).
            timelimit:     Maximum total seconds to wait before raising
                           TimeoutError (default: 3600).

        Returns:
            The task record dict when the task reaches a terminal state.

        Raises:
            RuntimeError:  If the API returns an error, or the task finishes
                           with status 'error' or 'canceled'.
            TimeoutError:  If the task does not finish within `timelimit` seconds.
        """
        deadline = time.monotonic() + timelimit
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"Background task {bt_id} did not complete within {timelimit}s"
                )

            data = self._request(
                "getUserBackgroundTasks",
                {"bt_id": bt_id},
            )

            tasks = data.get("response", {}).get("tasks", [])
            if isinstance(tasks, dict):
                tasks = [tasks]

            task = next((t for t in tasks if str(t.get("bt_id")) == str(bt_id)), None)
            if task is None:
                # Task no longer visible – treat as completed
                return {"bt_id": bt_id, "bt_status": "completed"}

            status = task.get("bt_status", "").lower()
            if status in ("completed", "error", "canceled", "cancelled"):
                if status not in ("completed",):
                    raise RuntimeError(
                        f"Background task {bt_id} finished with status '{status}': "
                        f"{task.get('bt_title', '')}"
                    )
                return task

            time.sleep(poll_interval)
