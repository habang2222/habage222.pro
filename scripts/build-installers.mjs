import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const downloads = path.join(root, 'downloads');
const hash = name => crypto.createHash('sha256').update(fs.readFileSync(path.join(downloads, name))).digest('hex');
const hybrid = source => `@echo off\r\nsetlocal\r\nset "HABANG_SETUP_FILE=%~f0"\r\npowershell.exe -NoProfile -Command "$s=[IO.File]::ReadAllText($env:HABANG_SETUP_FILE); & ([scriptblock]::Create(($s -split '(?m)^# POWERSHELL\\r?$',2)[1]))"\r\nset "HABANG_SETUP_EXIT=%errorlevel%"\r\necho.\r\npause\r\nexit /b %HABANG_SETUP_EXIT%\r\n# POWERSHELL\r\n${source.replace(/\r?\n/g, '\r\n')}\r\n`;

const psStart = `$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {`;
const psEnd = `
} catch {
  Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
  Write-Host 'Installation did not finish. See the guide at https://habang222.pro/'
  exit 1
}
exit 0`;

const extensions = [
  { file: 'LectureAlarm-Setup.cmd', name: 'lecture-alarm', version: 'v2.2.0', zip: 'cu-lms-lecture-alarm-v2.2.0.zip', guide: 'lecture-alarm.html', native: true },
  { file: 'RandomBackspace-Setup.cmd', name: 'random-backspace', version: 'f64bdb1', zip: 'random-password-backspace-f64bdb1.zip', guide: 'random-backspace.html', native: false }
];
for (const app of extensions) {
  const body = `${psStart}
  $appRoot = Join-Path $env:LOCALAPPDATA 'HabangTools\\${app.name}'
  $destination = Join-Path $appRoot '${app.version}'
  $guide = 'https://habang222.pro/${app.guide}'
  $chromePaths = @(
    (Join-Path $env:ProgramFiles 'Google\\Chrome\\Application\\chrome.exe'),
    (Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Google\\Chrome\\Application\\chrome.exe'),
    (Join-Path $env:LOCALAPPDATA 'Google\\Chrome\\Application\\chrome.exe')
  )
  $chrome = $chromePaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if (-not $chrome) { throw 'Google Chrome was not found. Install Chrome first, or use the ZIP and manual guide.' }
  # Use a new staging directory. Never delete or overwrite an installed extension.
  $stage = Join-Path $appRoot ('stage-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $stage -Force | Out-Null
  $archive = Join-Path $stage 'package.zip'
  Write-Host 'Downloading the extension package...'
  Invoke-WebRequest -UseBasicParsing -Uri 'https://habang222.pro/downloads/${app.zip}' -OutFile $archive
  if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne '${hash(app.zip)}') {
    throw 'The download checksum did not match. The package was not installed.'
  }
  $unpacked = Join-Path $stage 'extension'
  Expand-Archive -LiteralPath $archive -DestinationPath $unpacked
  $manifests = @(Get-ChildItem -LiteralPath $unpacked -Filter manifest.json -Recurse)
  if ($manifests.Count -ne 1) { throw 'Expected one extension manifest in the package.' }
  $extension = $manifests[0].Directory.FullName
  if (Test-Path -LiteralPath $destination) {
    foreach ($expectedFile in Get-ChildItem -LiteralPath $extension -File -Recurse) {
      $relative = $expectedFile.FullName.Substring($extension.Length + 1)
      $existingFile = Join-Path $destination $relative
      if (-not (Test-Path -LiteralPath $existingFile -PathType Leaf)) { throw 'The existing extension folder is incomplete. Use a separate folder with the ZIP download to reinstall.' }
      if ((Get-FileHash -LiteralPath $expectedFile.FullName).Hash -ne (Get-FileHash -LiteralPath $existingFile).Hash) { throw 'The existing extension folder was modified. Use a separate folder with the ZIP download to reinstall.' }
    }
    $extension = $destination
  } else {
    Move-Item -LiteralPath $extension -Destination $destination
    $extension = $destination
  }
  # Repeat runs reuse the folder only after checking all expected file hashes.
${app.native ? `  $nativeInstaller = Join-Path $extension '네이티브경고창_설치.ps1'
  if (-not (Test-Path -LiteralPath $nativeInstaller)) { throw 'Windows notification helper source is missing.' }
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $nativeInstaller
  if ($LASTEXITCODE -ne 0) { throw 'Windows notification helper registration failed.' }
` : ''}  try { Set-Clipboard -Value $extension } catch { Write-Host 'Could not copy the path. Copy it from the line below.' }
  Write-Host ''
  Write-Host '[READY] Extension files are prepared. Finish registration in Chrome:' -ForegroundColor Green
  Write-Host '1. Enable Developer mode at chrome://extensions/'
  Write-Host '2. Click Load unpacked and select this folder:'
  Write-Host $extension -ForegroundColor Cyan
  Write-Host '3. Refresh the open webpages. Keep this extension folder in place.'
  Start-Process -FilePath explorer.exe -ArgumentList ('"' + $extension + '"')
  Start-Process -FilePath $chrome -ArgumentList 'chrome://extensions/'
  Start-Process $guide
${psEnd}`;
  fs.writeFileSync(path.join(downloads, app.file), hybrid(body));
}

const linuxHash = hash('install-mglogwh.sh');
const mgBody = `${psStart}
  if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw 'Install WSL2 and Ubuntu-24.04 first. See https://habang222.pro/mglogwh.html' }
  $distros = ((& wsl.exe --list --quiet) -join [Environment]::NewLine).Replace([string][char]0, '')
  if ($LASTEXITCODE -ne 0 -or $distros -notmatch '(?m)^\\s*Ubuntu-24\\.04\\s*$') {
    throw 'Ubuntu-24.04 was not found. First run: wsl --install -d Ubuntu-24.04'
  }
  $stage = Join-Path $env:TEMP ('Habang-MGlogWH-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $stage | Out-Null
  $script = Join-Path $stage 'install-mglogwh.sh'
  Write-Host 'Downloading the Ubuntu installer...'
  Invoke-WebRequest -UseBasicParsing -Uri 'https://habang222.pro/downloads/install-mglogwh.sh' -OutFile $script
  if ((Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash -ne '${linuxHash}') { throw 'The download checksum did not match. Download a fresh installer from the website.' }
  $linuxPath = & wsl.exe -d Ubuntu-24.04 -- wslpath -a -u $script
  if ($LASTEXITCODE -ne 0 -or -not $linuxPath) { throw 'Could not access the downloaded installer from Ubuntu.' }
  Write-Host 'Ubuntu may request your Linux sudo password. The characters will not be displayed.'
  & wsl.exe -d Ubuntu-24.04 -- bash $linuxPath.Trim()
  if ($LASTEXITCODE -ne 0) { throw 'Ubuntu installation failed. Read the error above and the website guide.' }
  Write-Host 'Read the login token in Ubuntu: sudo cat /etc/mglogwh-controlroom/token'
  Start-Process 'http://127.0.0.1:8765'
${psEnd}`;
fs.writeFileSync(path.join(downloads, 'MGlogWH-Setup.cmd'), hybrid(mgBody));

const manifest = {
  description: 'Pinned packages and installer integrity checks for habang222.pro',
  sources: {
    MGlogWH: '5cb573ac5402ca7580fb4c8e0a3f30576a5d38d2',
    'MGlogWH-ControlRoom': '5f67113e7f9eea9c12d3105f42ae137723ab2c3e',
    'cu-lms-lecture-alarm': 'v2.2.0',
    'random-password-backspace': 'f64bdb1393717bda9787c3060b78565f1d9f9aa1'
  },
  sha256: Object.fromEntries(fs.readdirSync(downloads).filter(f => /\.(cmd|sh|zip)$/.test(f)).sort().map(f => [f, hash(f)]))
};
fs.writeFileSync(path.join(downloads, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
console.log('Created three setup helpers and download checksums.');
