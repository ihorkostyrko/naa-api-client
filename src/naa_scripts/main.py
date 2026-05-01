"""
NAA Scripts
Direct interaction with Nasuni Access Anywhere (formerly StorageMadeEasy) API.

Author: Ihor Kostyrko
Github: https://github.com/ihorkostyrko/naa-api-client
License: MIT
Copyright (c) 2026 Ihor Kostyrko
"""

import json
import os
import time
from os import urandom

import urllib3
from naa_client import NAAApiError, NAAClient

# Suppress SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Configuration ---
_config_path = os.path.join(os.path.dirname(__file__), "config.json")
with open(_config_path) as _f:
    _config = json.load(_f)

API_HOST = _config["api_host"]
USERNAME = _config["username"]
PASSWORD = _config["password"]


def print_table(items: list) -> None:
    """Print items as a formatted table: fi_id, fi_type, fi_name, fi_size.
    Folders (fi_type == '1') are listed before files (fi_type == '0').
    """
    # Sort: folders first (fi_type '1'), then files (fi_type '0')
    sorted_items = sorted(items, key=lambda x: 0 if x.get("fi_type") == "1" else 1)

    col_widths = {
        "fi_id": max(
            5, max((len(str(i.get("fi_id", ""))) for i in sorted_items), default=5)
        ),
        "fi_type": max(
            7, max((len(str(i.get("fi_type", ""))) for i in sorted_items), default=7)
        ),
        "fi_name": max(
            7, max((len(str(i.get("fi_name", ""))) for i in sorted_items), default=7)
        ),
        "fi_size": max(
            7, max((len(str(i.get("fi_size", ""))) for i in sorted_items), default=7)
        ),
    }

    header = (
        f"{'fi_id':<{col_widths['fi_id']}}  "
        f"{'fi_type':<{col_widths['fi_type']}}  "
        f"{'fi_name':<{col_widths['fi_name']}}  "
        f"{'fi_size':<{col_widths['fi_size']}}"
    )
    separator = "-" * len(header)

    print(header)
    print(separator)

    for item in sorted_items:
        fi_type_label = "folder" if item.get("fi_type") == "1" else "file"
        print(
            f"{str(item.get('fi_id', '')):<{col_widths['fi_id']}}  "
            f"{fi_type_label:<{col_widths['fi_type']}}  "
            f"{str(item.get('fi_name', '')):<{col_widths['fi_name']}}  "
            f"{str(item.get('fi_size', '')):<{col_widths['fi_size']}}"
        )


def create_temp_file(path: str, filename: str, size: int) -> None:
    """Create a temporary file with the specified name and size in bytes, filled with random data."""
    full_path = os.path.join(path, filename)
    chunk = 8 * 1024
    with open(full_path, "wb") as f:
        remaining = size
        while remaining > 0:
            f.write(urandom(min(chunk, remaining)))
            remaining -= chunk


def main() -> None:
    print("Authenticating...")
    client = NAAClient(API_HOST, USERNAME, PASSWORD)
    print(f"Token: {client.token}\n")

    print("Fetching root folder contents...")
    items = client.get_folder_contents(folder_id=0)
    print(f"Found {len(items)} item(s).\n")
    print_table(items)

    print("\nChecking if folder 'Nasuni files/Projects' exists...")
    result = client.check_path_exists("Nasuni files/Projects")
    if result.get("exists") == "y":
        folder_id = int(result["objectid"])
        print(f"Folder 'Nasuni files/Projects' found, fi_id: {folder_id}")
    else:
        print("Folder 'Nasuni files/Projects' not found")
        return -1

    print(f"\nRefreshing folder fi_id={folder_id}...")
    start_time = time.time()
    client.refresh_folder(folder_id=folder_id)
    end_time = time.time()
    print(f"Folder refresh completed in {end_time - start_time:.2f} seconds.")

    temp_filename = "file1.tmp"
    temp_path = os.path.join(os.path.dirname(__file__), "tmp")
    os.makedirs(temp_path, exist_ok=True)
    print(f"\nCreating temp file '{temp_filename}'...")
    create_temp_file(temp_path, temp_filename, 1024)
    print(f"Temp file created: {os.path.join(temp_path, temp_filename)}")

    print(f"\nUploading '{temp_filename}' to folder fi_id={folder_id}...")
    result = client.upload_file(os.path.join(temp_path, temp_filename), folder_id)
    uploaded_fi_id = result["fi_id"]
    print(f"File '{temp_filename}' uploaded successfully: fi_id={uploaded_fi_id}")

    print(f"\nRenaming fi_id={uploaded_fi_id} to 'file2.tmp'...")
    renamed = client.rename_file(uploaded_fi_id, "file2.tmp")
    print(f"File renamed to: {renamed['fi_name']}")

    download_dest = os.path.join(temp_path, "file2.tmp")
    print(f"\nDownloading fi_id={uploaded_fi_id} to '{download_dest}'...")
    client.download_file(uploaded_fi_id, download_dest)
    print(f"File downloaded to: {download_dest}")

    print(
        f"\nCreating shared link for fi_id={uploaded_fi_id} (password='12345', expires in 7 days)..."
    )
    share_url = client.get_file_url(uploaded_fi_id, password="12345", days=7)
    print(f"Shared link: {share_url}")

    print(f"\nCreating folder 'test_folder1' inside fi_id={folder_id}...")
    result = client.create_folder("test_folder1", folder_id)
    test_folder1_id = int(result["fi_id"])
    print(f"Result: {result}")

    print(f"\nCreating folder 'test_folder2' inside fi_id={folder_id}...")
    result = client.create_folder("test_folder2", folder_id)
    test_folder2_id = int(result["fi_id"])
    print(f"Result: {result}")

    print(
        f"\nCopying fi_id={uploaded_fi_id} into test_folder1 (fi_id={test_folder1_id})..."
    )
    result = client.copy_file(uploaded_fi_id, test_folder1_id)
    print(f"Result: {result}")
    bt_id = (result.get("response") or {}).get("backgroundtaskid")
    if bt_id:
        print(f"Waiting for background task {bt_id} to complete...")
        task = client.await_task_completion(int(bt_id))
        print(f"Background task finished: {task}")
    else:
        print("Copy completed synchronously (no background task).")

    print(
        f"\nMoving test_folder1 (fi_id={test_folder1_id}) into test_folder2 (fi_id={test_folder2_id})..."
    )
    result = client.move_folder(test_folder1_id, test_folder2_id)
    print(f"Result: {result}")
    # doMoveFolder returns background task IDs for moved folders in foldertasks: {fi_id: task_id}
    # (only folder moves appear here; file moves use a separate internal background task)
    folder_tasks = result.get("foldertasks") or {}
    bt_id = next(iter(folder_tasks.values()), None) if folder_tasks else None
    if bt_id:
        print(f"Waiting for background task {bt_id} to complete...")
        task = client.await_task_completion(int(bt_id))
        print(f"Background task finished: {task}")

        # The move operation is actually a copy followed by delete
        # So we wait for the deletion tasks to complete as well.
        client.await_all_tasks_completion(task_type="DeleteFileObjects")
        print("All deletion tasks are completed")
    else:
        print("Move completed synchronously (no background task).")

    print(
        f"\nDeleting test_folder2 (fi_id={test_folder2_id}) "
        "(also removes test_folder1 and the copied file inside it)..."
    )

    result = None
    for attempt in range(1, 6):
        try:
            result = client.delete_folder(test_folder2_id)
            break
        except NAAApiError as e:
            print(f"Attempt {attempt}: Error deleting folder: {e}")
            if e.status == "error_background" and attempt < 5:
                # Folder is busy — wait and retry
                print("Folder is busy, retrying in 2s...")
                time.sleep(2)
            else:
                raise

    print(f"Result: {result}")
    # doDeleteFolder returns task ID in response.backgroundtask (0 = synchronous)
    bt_id = (result.get("response") or {}).get("backgroundtask") or 0
    if bt_id:
        print(f"Waiting for background task {bt_id} to complete...")
        task = client.await_task_completion(int(bt_id))
        print(f"Background task finished: {task}")
    else:
        print("Delete completed synchronously (no background task).")

    print(f"\nDeleting fi_id={uploaded_fi_id} ('file2.tmp')...")
    result = client.delete_file(uploaded_fi_id)
    bt_id = (result.get("response") or {}).get("backgroundtask") or 0
    if bt_id:
        print(f"Waiting for background task {bt_id} to complete...")
        task = client.await_task_completion(int(bt_id))
        print(f"Background task finished: {task}")
    else:
        print("File 'file2.tmp' deleted successfully.")


if __name__ == "__main__":
    main()
