param(
    [switch] $SkipPyInstallerInstall
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Version = (Get-Content -Raw (Join-Path $Root "VERSION")).Trim()
$AppName = "Salem Google TV Emulator"
$AppExe = "$AppName.exe"
$SetupPackageName = "Salem_Google_TV_Emulator_Setup_v$Version.exe"
$PortablePackageName = "Salem_Google_TV_Emulator_Portable_v$Version.zip"
$SourcePackageName = "Salem_Google_TV_Emulator-v$Version-source.zip"
$IconPath = Join-Path $Root "assets\salem_google_tv_emulator.ico"
$AssetsPath = Join-Path $Root "assets"
$ReleaseDir = Join-Path $Root "release_github"
$LocalDir = Join-Path $Root "build_local"
$LocalAppDir = Join-Path $LocalDir $AppName
$BuildDir = Join-Path $Root "build"
$DistDir = Join-Path $Root "dist"

function Resolve-InWorkspace {
    param([Parameter(Mandatory=$true)][string] $Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    if ($full.Equals($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate on workspace root: $full"
    }
    if (-not $full.StartsWith($Root + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside workspace: $full"
    }
    return $full
}

function Reset-Directory {
    param([Parameter(Mandatory=$true)][string] $Path)
    $full = Resolve-InWorkspace $Path
    if (Test-Path $full) {
        Remove-Item -LiteralPath $full -Recurse -Force
    }
    New-Item -ItemType Directory -Path $full | Out-Null
}

function Assert-Exists {
    param([Parameter(Mandatory=$true)][string] $Path)
    if (-not (Test-Path $Path)) {
        throw "Missing expected release file: $Path"
    }
}

function Copy-ReleaseDoc {
    param([Parameter(Mandatory=$true)][string] $Name)
    Copy-Item -LiteralPath (Join-Path $Root $Name) -Destination (Join-Path $ReleaseDir $Name) -Force
}

function Assert-ZipPrivacy {
    param([Parameter(Mandatory=$true)][string] $Path)
    $entries = tar -tf $Path
    $forbidden = $entries | Where-Object {
        $_ -match '(^|/)(__pycache__|logs?|cache|cookies?|tokens?|settings\.json|\.env)(/|$)' -or
        $_ -match '(api[_-]?key|secret|credential|runtime[_-]?data)'
    }
    if ($forbidden) {
        throw "Privacy scan failed for $Path. Forbidden entries: $($forbidden -join ', ')"
    }
}

Write-Host "Building $AppName v$Version"

Assert-Exists $IconPath
Assert-Exists $AssetsPath

if (-not $SkipPyInstallerInstall) {
    & py -3 -m PyInstaller --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & py -3 -m pip install pyinstaller
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller installation failed."
        }
    }
}

Reset-Directory $BuildDir
Reset-Directory $DistDir
Reset-Directory $LocalDir
Reset-Directory $ReleaseDir

Write-Host "Running compile check..."
& py -3 -m compileall main.py salem_tv_box_emulator
if ($LASTEXITCODE -ne 0) {
    throw "compileall failed."
}

Write-Host "Building application EXE..."
& py -3 -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name $AppName `
    --icon $IconPath `
    --add-data "$AssetsPath;assets" `
    --version-file (Join-Path $Root "build_tools\version_info_app.txt") `
    (Join-Path $Root "main.py")
if ($LASTEXITCODE -ne 0) {
    throw "Application PyInstaller build failed."
}

$AppDistDir = Join-Path $DistDir $AppName
$BuiltExe = Join-Path $AppDistDir $AppExe
Assert-Exists $BuiltExe

New-Item -ItemType Directory -Path $LocalAppDir | Out-Null
Copy-Item -Path (Join-Path $AppDistDir "*") -Destination $LocalAppDir -Recurse -Force
Copy-Item -LiteralPath (Join-Path $Root "README.md") -Destination $LocalAppDir -Force
Copy-Item -LiteralPath (Join-Path $Root "CHANGELOG.md") -Destination $LocalAppDir -Force
Copy-Item -LiteralPath (Join-Path $Root "RELEASE.md") -Destination $LocalAppDir -Force
Copy-Item -LiteralPath (Join-Path $Root "VERSION") -Destination $LocalAppDir -Force
Copy-Item -LiteralPath (Join-Path $Root "version.json") -Destination $LocalAppDir -Force

Write-Host "Creating Portable.zip..."
$PortableZip = Join-Path $ReleaseDir "Portable.zip"
Compress-Archive -Path $LocalAppDir -DestinationPath $PortableZip -Force

Write-Host "Creating Source.zip..."
$SourceRoot = Join-Path $BuildDir "source_package"
$SourceDir = Join-Path $SourceRoot "$AppName Source"
New-Item -ItemType Directory -Path $SourceDir -Force | Out-Null
foreach ($item in @("main.py", "requirements.txt", "run.bat", "README.md", "CHANGELOG.md", "RELEASE.md", "RELEASE_CHECKLIST.md", "VERSION", "version.json")) {
    Copy-Item -LiteralPath (Join-Path $Root $item) -Destination $SourceDir -Force
}
Copy-Item -LiteralPath (Join-Path $Root "salem_tv_box_emulator") -Destination $SourceDir -Recurse -Force
Copy-Item -LiteralPath (Join-Path $Root "build_tools") -Destination $SourceDir -Recurse -Force
if (Test-Path (Join-Path $Root "assets")) {
    Copy-Item -LiteralPath (Join-Path $Root "assets") -Destination $SourceDir -Recurse -Force
}
Get-ChildItem -Path $SourceDir -Recurse -Directory -Filter "__pycache__" | ForEach-Object {
    $candidate = Resolve-InWorkspace $_.FullName
    Remove-Item -LiteralPath $candidate -Recurse -Force
}
$SourceZip = Join-Path $ReleaseDir "Source.zip"
Compress-Archive -Path $SourceDir -DestinationPath $SourceZip -Force

Copy-ReleaseDoc "README.md"
Copy-ReleaseDoc "CHANGELOG.md"
Copy-ReleaseDoc "RELEASE.md"
Copy-ReleaseDoc "RELEASE_CHECKLIST.md"
Copy-ReleaseDoc "version.json"

Write-Host "Building Setup.exe..."
& py -3 -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "Setup" `
    --icon $IconPath `
    --version-file (Join-Path $Root "build_tools\version_info_installer.txt") `
    --add-data "$PortableZip;." `
    (Join-Path $Root "build_tools\installer.py")
if ($LASTEXITCODE -ne 0) {
    throw "Installer PyInstaller build failed."
}

$SetupExe = Join-Path $DistDir "Setup.exe"
Assert-Exists $SetupExe
Copy-Item -LiteralPath $SetupExe -Destination (Join-Path $ReleaseDir "Setup.exe") -Force
Copy-Item -LiteralPath (Join-Path $ReleaseDir "Setup.exe") -Destination (Join-Path $ReleaseDir $SetupPackageName) -Force
Copy-Item -LiteralPath $PortableZip -Destination (Join-Path $ReleaseDir $PortablePackageName) -Force
Copy-Item -LiteralPath $SourceZip -Destination (Join-Path $ReleaseDir $SourcePackageName) -Force

Assert-Exists (Join-Path $ReleaseDir "Setup.exe")
Assert-Exists $PortableZip
Assert-Exists $SourceZip
Assert-Exists (Join-Path $ReleaseDir $SetupPackageName)
Assert-Exists (Join-Path $ReleaseDir $PortablePackageName)
Assert-Exists (Join-Path $ReleaseDir $SourcePackageName)
Assert-Exists (Join-Path $ReleaseDir "version.json")
Assert-Exists (Join-Path $ReleaseDir "README.md")
Assert-Exists (Join-Path $ReleaseDir "CHANGELOG.md")
Assert-Exists (Join-Path $ReleaseDir "RELEASE.md")
Assert-Exists (Join-Path $ReleaseDir "RELEASE_CHECKLIST.md")
Assert-Exists (Join-Path $LocalAppDir $AppExe)

$ReleaseVersion = (Get-Content -Raw (Join-Path $ReleaseDir "version.json") | ConvertFrom-Json).version
$ReadmeText = Get-Content -Raw (Join-Path $ReleaseDir "README.md")
$ChangelogText = Get-Content -Raw (Join-Path $ReleaseDir "CHANGELOG.md")
$AppProductVersion = (Get-Item (Join-Path $LocalAppDir $AppExe)).VersionInfo.ProductVersion
$SetupProductVersion = (Get-Item (Join-Path $ReleaseDir "Setup.exe")).VersionInfo.ProductVersion

if ($ReleaseVersion -ne $Version) {
    throw "version.json mismatch: $ReleaseVersion"
}
if (-not $ReadmeText.Contains("v$Version")) {
    throw "README.md does not contain v$Version"
}
if (-not $ChangelogText.Contains("v$Version")) {
    throw "CHANGELOG.md does not contain v$Version"
}
if (-not $AppProductVersion.StartsWith("$Version.")) {
    throw "Application EXE metadata mismatch: $AppProductVersion"
}
if (-not $SetupProductVersion.StartsWith("$Version.")) {
    throw "Installer metadata mismatch: $SetupProductVersion"
}

Assert-ZipPrivacy $PortableZip
Assert-ZipPrivacy $SourceZip
Assert-ZipPrivacy (Join-Path $ReleaseDir $PortablePackageName)
Assert-ZipPrivacy (Join-Path $ReleaseDir $SourcePackageName)

Write-Host ""
Write-Host "Local build: $LocalAppDir"
Write-Host "Release package: $ReleaseDir"
Write-Host "App EXE ProductVersion: $AppProductVersion"
Write-Host "Setup.exe ProductVersion: $SetupProductVersion"
Write-Host "v$Version release artifacts created."
