param([string]$Helper, [string]$Scenario, [string]$TestRoot)
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Utility
Import-Module Microsoft.PowerShell.Archive
$env:LOCALAPPDATA = Join-Path $TestRoot 'localappdata'
$env:TEMP = Join-Path $TestRoot 'temp'
New-Item -ItemType Directory -Path $env:LOCALAPPDATA,$env:TEMP -Force | Out-Null
$global:taskScenario = $Scenario
$global:taskLog = Join-Path $TestRoot 'calls.txt'
$global:taskDownloadRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'downloads'
function Write-Call([string]$Text) { Add-Content -LiteralPath $global:taskLog -Value $Text }
function Invoke-WebRequest {
  param([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile)
  Write-Call ('download ' + $Uri)
  if ($global:taskScenario -eq 'corrupt') {
    [IO.File]::WriteAllText($OutFile, 'corrupt download')
  } else {
    Copy-Item -LiteralPath (Join-Path $global:taskDownloadRoot ([Uri]$Uri).Segments[-1]) -Destination $OutFile
  }
}
function Test-Path {
  [CmdletBinding(DefaultParameterSetName='Path')]
  param(
    [Parameter(Position=0,ParameterSetName='Path')][string[]]$Path,
    [Parameter(ParameterSetName='LiteralPath')][string[]]$LiteralPath,
    [Alias('Type')][string]$PathType,
    [switch]$IsValid
  )
  if ($LiteralPath -and $LiteralPath[0] -like '*\Google\Chrome\Application\chrome.exe') { return ($global:taskScenario -ne 'missing-chrome') }
  Microsoft.PowerShell.Management\Test-Path @PSBoundParameters
}
function Start-Process {
  param([string]$FilePath, [string[]]$ArgumentList)
  Write-Call ('open ' + $FilePath + ' ' + ($ArgumentList -join ' '))
}
function Set-Clipboard {
  param([string]$Value)
  if ($Value -notlike ($env:LOCALAPPDATA + '*')) { throw 'Unexpected extension path.' }
  if (-not (Microsoft.PowerShell.Management\Test-Path -LiteralPath (Join-Path $Value 'manifest.json'))) { throw 'Manifest missing from install path.' }
  Write-Call ('clipboard ' + $Value)
}
function powershell.exe {
  Write-Call 'native-helper-mock'
  $global:LASTEXITCODE = 0
  if ($global:taskScenario -eq 'native-failure') { $global:LASTEXITCODE = 1 }
}
function wsl.exe {
  Write-Call ('wsl ' + ($args -join ' '))
  $global:LASTEXITCODE = 0
  if ($args[0] -eq '--list') {
    if ($global:taskScenario -eq 'missing-wsl-distro') { return 'other-distro' }
    return 'Ubuntu-24.04'
  }
  if ($args -contains 'wslpath') { return '/tmp/mock-installer.sh' }
  if ($global:taskScenario -eq 'linux-failure') { $global:LASTEXITCODE = 1 }
}
$body = ([IO.File]::ReadAllText($Helper) -split '(?m)^# POWERSHELL\r?$',2)[1]
if (-not $body) { throw 'Hybrid script marker failed.' }
& ([scriptblock]::Create($body))
