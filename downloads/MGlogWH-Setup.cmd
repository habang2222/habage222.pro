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
  if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw 'Install WSL2 and Ubuntu-24.04 first. See https://habang222.pro/mglogwh.html' }
  $distros = ((& wsl.exe --list --quiet) -join [Environment]::NewLine).Replace([string][char]0, '')
  if ($LASTEXITCODE -ne 0 -or $distros -notmatch '(?m)^\s*Ubuntu-24\.04\s*$') {
    throw 'Ubuntu-24.04 was not found. First run: wsl --install -d Ubuntu-24.04'
  }
  $stage = Join-Path $env:TEMP ('Habang-MGlogWH-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $stage | Out-Null
  $script = Join-Path $stage 'install-mglogwh.sh'
  Write-Host 'Downloading the Ubuntu installer...'
  Invoke-WebRequest -UseBasicParsing -Uri 'https://habang222.pro/downloads/install-mglogwh.sh' -OutFile $script
  if ((Get-FileHash -LiteralPath $script -Algorithm SHA256).Hash -ne '45c3f04f1ad23603cf11a370f988c27ecdcfef3e858cc3c848586086c659f88f') { throw 'The download checksum did not match. Download a fresh installer from the website.' }
  $linuxPath = & wsl.exe -d Ubuntu-24.04 -- wslpath -a -u $script
  if ($LASTEXITCODE -ne 0 -or -not $linuxPath) { throw 'Could not access the downloaded installer from Ubuntu.' }
  Write-Host 'Ubuntu may request your Linux sudo password. The characters will not be displayed.'
  & wsl.exe -d Ubuntu-24.04 -- bash $linuxPath.Trim()
  if ($LASTEXITCODE -ne 0) { throw 'Ubuntu installation failed. Read the error above and the website guide.' }
  Write-Host 'Read the login token in Ubuntu: sudo cat /etc/mglogwh-controlroom/token'
  Start-Process 'http://127.0.0.1:8765'

} catch {
  Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
  Write-Host 'Installation did not finish. See the guide at https://habang222.pro/'
  exit 1
}
exit 0
