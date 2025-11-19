import os
import sys
import shutil
import tempfile
import requests
import subprocess
import time

GITHUB_REPO = "agustinaponte/ding"   # <--- change if needed
ASSET_NAME = "ding.exe"              # must match your release asset

def parse_version(v):
    return tuple(map(int, v.split(".")))

def fetch_latest_release():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.json()

def run_update_check(current_version):
    print("Checking for updates...\n")

    try:
        release = fetch_latest_release()
    except Exception as e:
        print(f"❌ Failed to query GitHub releases: {e}")
        return

    latest_tag = release.get("tag_name", "").lstrip("v")
    print(f"Current version: {current_version}")
    print(f"Latest version:  {latest_tag}")

    try:
        if parse_version(latest_tag) <= parse_version(current_version):
            print("\n✔ You already have the latest version.")
            return
    except Exception:
        print("\n⚠ Version format error, update skipped.")
        return

    assets = release.get("assets", [])
    download_url = None
    for a in assets:
        if a["name"].lower() == ASSET_NAME.lower():
            download_url = a["browser_download_url"]
            break

    if not download_url:
        print(f"\n❌ Asset {ASSET_NAME} not found in latest release.")
        return

    print(f"\nNew version available: {latest_tag}")
    choice = input("Do you want to download and install it? (y/n): ").strip().lower()
    if choice != "y":
        print("Update cancelled.")
        return

    print("\nDownloading...")

    temp_dir = tempfile.mkdtemp()
    temp_exe = os.path.join(temp_dir, ASSET_NAME)

    try:
        with requests.get(download_url, stream=True) as r:
            r.raise_for_status()
            with open(temp_exe, "wb") as f:
                shutil.copyfileobj(r.raw, f)
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return

    print("Download complete.")

    current_exe = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]

    print(f"\nUpdating: {current_exe}")
    try:
        # Windows cannot overwrite a running executable.
        # So we spawn a small bat script that waits then replaces the exe.
        bat_path = os.path.join(temp_dir, "update.bat")
        with open(bat_path, "w") as bat:
            bat.write(f"""
@echo off
timeout /t 1 >nul
copy /y "{temp_exe}" "{current_exe}" >nul
start "" "{current_exe}"
rmdir /s /q "{temp_dir}"
""")
        subprocess.Popen(["cmd", "/c", bat_path], shell=True)
        print("\n✔ Update applied. Restarting...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Failed to install update: {e}")
