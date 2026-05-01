### # NAA API Client (Nasuni Access Anywhere)

A lightweight Python client and demonstration script for the **Nasuni Access Anywhere (NAA)** API.

## 📝 Background
Nasuni Access Anywhere (NAA) was previously known as **StorageMadeEasy (SME)** and originally started as **SMEStorage**. This project provides a simple implementation to interact with NAA API.

This repository is intended for developers who want to understand the core logic of the NAA API and integrate cloud-spanning capabilities into their own applications.

## ✨ Features
* **Authentication**: Easy token retrieval via `getToken`.
* **File Management**: Create folders, list files, refresh folders, upload files, download files, copy files/folders, and manage metadata.
* **Cloud Integration**: Compatible with the unified namespace provided by NAA.

## 🚀 Quick Start

### Prerequisites
Python 3.x

### Installation
1. Clone the repository:
```bash
git clone https://github.com/ihorkostyrko/naa-api-client.git
cd naa-api-client
```

2. Install dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```


### Configuration
Create the `config.json` config file.
Example of content:
```bash
{
    api_host: "your-org.storagemadeeasy.com",
    username: "your_username",
    password: "your_password"
}
```


### Usage
```bash
python src/naa_scripts/main.py
```

This will do:
- Get API token.
- Fetch root folder contents.
- Check if the 'Nasuni files/Projects' folder exists and print the folder ID (`fi_id`) if it exists.
- Refresh the 'Nasuni files/Projects' folder and wait while the refresh will be completed.
- Upload a temporary file to the 'Nasuni files/Projects' folder.
- Rename the uploaded file to `file2.tmp`.
- Download the uploaded file and save it to a temporary directory.
- Create a shared link with a password and expiration date for the uploaded file.
- Create the `test_folder1` folder inside the 'Nasuni files/Projects' folder.
- Create the `test_folder2` folder inside the 'Nasuni files/Projects' folder.
- Copy the `file2.tmp` file into the `test_folder1` folder.
- Move the `test_folder1` folder into the `test_folder1` folder.
- Delete the `test_folder2` folder.
- Delete the `file2.tmp` file from the 'Nasuni files/Projects' folder.


## 📫 Contact me
If you have questions about this NAA API client, you can reach me via:
* **LinkedIn**: https://www.linkedin.com/in/ihor-o-kostyrko/
