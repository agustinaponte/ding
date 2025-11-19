# update_checker.py
import sys
import requests
import tempfile
import subprocess
import os


GITHUB_API_LATEST = 'https://api.github.com/repos/agustinaponte/ding/releases/latest'


def check_and_update(interactive=True):
    r = requests.get(GITHUB_API_LATEST)
    r.raise_for_status()
    release = r.json()
    tag = release['tag_name']
    assets = release.get('assets', [])
    # find msi or exe asset
    for a in assets:
        if a['name'].endswith('.msi'):
            download_url = a['browser_download_url']
            print(f"Latest release: {tag} -> {a['name']}")
            if interactive:
                ans = input('Download and install? [y/N]: ').strip().lower()
                if ans != 'y':
                    print('Update cancelled.')
                    return False
        # download
        fd, tmp = tempfile.mkstemp(suffix='.msi')
        os.close(fd)
        with requests.get(download_url, stream=True) as resp:
          resp.raise_for_status()
          with open(tmp, 'wb') as f:
            for chunk in resp.iter_content(8192):
              f.write(chunk)
        print('Downloaded to', tmp)
        # run installer (interactive)
        subprocess.run(['msiexec', '/i', tmp])
        return True
    print('No msi asset found in latest release')
    return False


if __name__ == '__main__':
    check_and_update()