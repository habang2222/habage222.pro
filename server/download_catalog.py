"""Explicit program/file allowlist; clients cannot choose filesystem paths or URLs."""
from pathlib import Path
import hashlib
import json
import os

PROGRAMS = {
    'photo-sorter': {'name': '사진 빠른 분류', 'defaultFile': 'PhotoSorter.apk', 'files': ['PhotoSorter.apk']},
    'mglogwh': {'name': 'MGlogWH + Control Room', 'defaultFile': 'MGlogWH-Setup.cmd', 'files': ['MGlogWH-Setup.cmd', 'install-mglogwh.sh']},
    'lecture-alarm': {'name': '싸강 완료 알림', 'defaultFile': 'cu-lms-lecture-alarm-v2.2.0.zip', 'files': ['LectureAlarm-Setup.cmd', 'cu-lms-lecture-alarm-v2.2.0.zip']},
    'random-backspace': {'name': '랜덤 백스페이스', 'defaultFile': 'random-password-backspace-f64bdb1.zip', 'files': ['RandomBackspace-Setup.cmd', 'random-password-backspace-f64bdb1.zip']},
}


def resolve_file(site_root, program, filename):
    if program not in PROGRAMS or filename not in PROGRAMS[program]['files']:
        return None
    if filename == 'PhotoSorter.apk':
        base = Path(os.getenv('ARTIFACT_ROOT', str(Path(site_root).parent / 'artifacts')))
    else:
        base = Path(site_root) / 'downloads'
    file = base / filename
    return file if file.is_file() else None


def catalog(site_root):
    manifest = Path(site_root) / 'downloads/manifest.json'
    hashes = json.loads(manifest.read_text(encoding='utf-8')).get('sha256', {}) if manifest.is_file() else {}
    hashes['PhotoSorter.apk'] = 'a337de9b10257591402aecb7569c983db2442f4d91d219e64ab2bf3545d3e35a'
    return [{'id': program, 'name': data['name'], 'defaultFile': data['defaultFile'], 'files': [
        {'name': filename, 'available': bool(resolve_file(site_root, program, filename)),
         'size': resolve_file(site_root, program, filename).stat().st_size if resolve_file(site_root, program, filename) else None,
         'sha256': hashes.get(filename), 'siteUrl': '/downloads/' + filename,
         'apiUrl': f'/api/v1/programs/{program}/files/{filename}'} for filename in data['files']]} for program, data in PROGRAMS.items()]
