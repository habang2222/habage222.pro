@echo off
setlocal
set "HABANG_SETUP_FILE=%~f0"
powershell.exe -NoProfile -Command "$s=[IO.File]::ReadAllText($env:HABANG_SETUP_FILE); & ([scriptblock]::Create(($s -split '(?m)^# POWERSHELL\r?$',2)[1]))"
set "HABANG_SETUP_EXIT=%errorlevel%"
echo.
pause
exit /b %HABANG_SETUP_EXIT%
# POWERSHELL
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
  $appRoot = Join-Path $env:LOCALAPPDATA 'HabangTools\lecture-alarm'
  $destination = Join-Path $appRoot 'v2.2.0'
  $guide = 'https://habang222.pro/lecture-alarm.html'
  $chromePaths = @(
    (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
    (Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) 'Google\Chrome\Application\chrome.exe'),
    (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe')
  )
  $chrome = $chromePaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
  if (-not $chrome) { throw 'Google Chrome was not found. Install Chrome first, or use the ZIP and manual guide.' }
  # Use a new staging directory. Never delete or overwrite an installed extension.
  $stage = Join-Path $appRoot ('stage-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $stage -Force | Out-Null
  $archive = Join-Path $stage 'package.zip'
  Write-Host 'Downloading the extension package...'
  Invoke-WebRequest -UseBasicParsing -Uri 'https://habang222.pro/downloads/cu-lms-lecture-alarm-v2.2.0.zip' -OutFile $archive
  if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne 'cfe3528280187fdf13a12b699c9152089c24c5bbc508eda3c8f16f8197ec5cf0') {
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
  $nativeInstaller = Join-Path $extension '네이티브경고창_설치.ps1'
  if (-not (Test-Path -LiteralPath $nativeInstaller)) { throw 'Windows notification helper source is missing.' }
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $nativeInstaller
  if ($LASTEXITCODE -ne 0) { throw 'Windows notification helper registration failed.' }
  try { Set-Clipboard -Value $extension } catch { Write-Host 'Could not copy the path. Copy it from the line below.' }
  Write-Host ''
  Write-Host '[READY] Extension files are prepared. Finish registration in Chrome:' -ForegroundColor Green
  Write-Host '1. Enable Developer mode at chrome://extensions/'
  Write-Host '2. Click Load unpacked and select this folder:'
  Write-Host $extension -ForegroundColor Cyan
  Write-Host '3. Refresh the open webpages. Keep this extension folder in place.'
  Start-Process -FilePath explorer.exe -ArgumentList ('"' + $extension + '"')
  Start-Process -FilePath $chrome -ArgumentList 'chrome://extensions/'
  Start-Process $guide

} catch {
  Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
  Write-Host 'Installation did not finish. See the guide at https://habang222.pro/'
  exit 1
}
exit 0
