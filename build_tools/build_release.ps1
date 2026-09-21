param([switch] $ReuseEnvironment)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$EnvRoot = Join-Path $Root '.venv-release'
if (-not $ReuseEnvironment -and (Test-Path -LiteralPath $EnvRoot)) {
    $Resolved = (Resolve-Path -LiteralPath $EnvRoot).Path
    if ($Resolved -ne (Join-Path $Root '.venv-release')) { throw 'Unexpected build environment path' }
    Remove-Item -LiteralPath $Resolved -Recurse -Force
}
if (-not (Test-Path -LiteralPath $EnvRoot)) {
    & py -3.14 -m venv $EnvRoot
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.14.4 x64 on the build computer only.' }
}
$Python = Join-Path $EnvRoot 'Scripts\python.exe'
& $Python -m pip install --disable-pip-version-check -r (Join-Path $Root 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw 'Pinned dependency installation failed' }
Push-Location $Root
try {
    & $Python -m build_tools.release
    if ($LASTEXITCODE -ne 0) { throw 'Build failed; existing release outputs were not replaced.' }
} finally { Pop-Location }
