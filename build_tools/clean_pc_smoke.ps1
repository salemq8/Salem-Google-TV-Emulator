param([Parameter(Mandatory=$true)][string] $Exe, [string] $Output = "$env:TEMP\Salem-clean-PC")
$ErrorActionPreference = 'Stop'
$App = (Resolve-Path -LiteralPath $Exe).Path
New-Item -ItemType Directory -Path $Output -Force | Out-Null
$Report = Join-Path $Output 'startup.json'
$env:PATH = "$env:SystemRoot\System32"
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
$env:QT_PLUGIN_PATH = 'C:\nonexistent-foreign-qt\plugins'
$Process = Start-Process -FilePath $App -ArgumentList @('--self-test', "`"$Report`"") -WindowStyle Hidden -Wait -PassThru
if ($Process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Report)) { throw "Startup failed. See $Output and Salem startup logs." }
$Result = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
if (-not $Result.ok) { throw ($Result | ConvertTo-Json) }
Write-Output ($Result | ConvertTo-Json -Depth 6)
