"""Fetch the pinned first-party APK into the non-public artifact directory."""
import argparse
import hashlib
from pathlib import Path
import requests

URL = 'https://github.com/habang2222/habage222.pro/releases/download/v1.2.0/PhotoSorter.apk'
SHA256 = 'a337de9b10257591402aecb7569c983db2442f4d91d219e64ab2bf3545d3e35a'


def fetch(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / 'PhotoSorter.apk'
    if file.exists() and hashlib.sha256(file.read_bytes()).hexdigest() == SHA256:
        return file
    response = requests.get(URL, timeout=60)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != SHA256:
        raise RuntimeError('APK integrity check failed')
    temporary = directory / 'PhotoSorter.apk.part'
    temporary.write_bytes(response.content)
    temporary.replace(file)
    return file


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default='/srv/files/artifacts')
    args = parser.parse_args()
    print(fetch(args.directory))
