$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$workspace = Join-Path $tempRoot ('habang-pages-' + [guid]::NewGuid().ToString('N'))
$stage = Join-Path $workspace 'static'
$checkout = Join-Path $workspace 'checkout'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program exited with status $LASTEXITCODE"
    }
}

New-Item -ItemType Directory -Path $workspace -Force | Out-Null
try {
    Invoke-Checked 'node' @((Join-Path $source 'edge/build-fallback.mjs'), $stage)
    foreach ($required in @('index.html', 'community.js', 'portal.js', '.nojekyll')) {
        if (-not (Test-Path -LiteralPath (Join-Path $stage $required) -PathType Leaf)) {
            throw "Static output is missing $required"
        }
    }
    $forbidden = Get-ChildItem -LiteralPath $stage -Recurse -File | Where-Object {
        $_.Extension -match '^\.(apk|zip|exe|msi|cmd|sh|db|sqlite3?)$' -or
        $_.Name -match '^(\.env|CNAME)$'
    }
    if ($forbidden) { throw 'Static output contains a forbidden file type' }

    Invoke-Checked 'git' @('clone', '--quiet', 'https://github.com/habang2222/habang222-pages.git', $checkout)
    $checkoutResolved = (Resolve-Path -LiteralPath $checkout).Path
    $workspaceResolved = (Resolve-Path -LiteralPath $workspace).Path
    if (-not $checkoutResolved.StartsWith($workspaceResolved + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Checkout is outside the temporary workspace'
    }

    Invoke-Checked 'git' @('-C', $checkoutResolved, 'rm', '-r', '--quiet', '--', '.')
    Get-ChildItem -LiteralPath $stage -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $checkoutResolved -Recurse -Force
    }
    Invoke-Checked 'git' @('-C', $checkoutResolved, 'add', '-A')
    & git -C $checkoutResolved diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Output 'Public static fallback is already current.'
        return
    }
    if ($LASTEXITCODE -ne 1) { throw 'Could not inspect the staged changes' }
    Invoke-Checked 'git' @('-C', $checkoutResolved, '-c', 'user.name=Habang deployment',
        '-c', 'user.email=41898282+github-actions[bot]@users.noreply.github.com',
        'commit', '--quiet', '-m', 'Refresh static offline fallback')
    Invoke-Checked 'git' @('-C', $checkoutResolved, 'push', '--quiet', 'origin', 'main')
    Write-Output 'Updated https://habang2222.github.io/habang222-pages/'
} finally {
    $target = [System.IO.Path]::GetFullPath($workspace)
    if ($target.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
        $target -ne $tempRoot -and (Test-Path -LiteralPath $target)) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
