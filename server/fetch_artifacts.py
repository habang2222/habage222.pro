"""Verify a locally supplied APK before serving it behind membership checks."""
import argparse
import hashlib
from pathlib import Path
import shutil
import tempfile

SHA256 = 'a337de9b10257591402aecb7569c983db2442f4d91d219e64ab2bf3545d3e35a'


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def fetch(directory, source=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / 'PhotoSorter.apk'
    if destination.is_file() and digest(destination) == SHA256:
        return destination
    if source is None:
        raise RuntimeError('Supply the verified APK with --source; public GitHub releases are not used')
    source = Path(source)
    if not source.is_file() or digest(source) != SHA256:
        raise RuntimeError('APK source is missing or has an unexpected SHA-256')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.PhotoSorter-', delete=False) as output:
            temporary = Path(output.name)
            with source.open('rb') as input_file:
                shutil.copyfileobj(input_file, output)
        if digest(temporary) != SHA256:
            raise RuntimeError('Copied APK failed SHA-256 verification')
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default='/srv/files/artifacts')
    parser.add_argument('--source', help='private local copy of PhotoSorter.apk')
    args = parser.parse_args()
    print(fetch(args.directory, args.source))
