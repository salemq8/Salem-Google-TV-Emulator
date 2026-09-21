# Building Salem Google TV Emulator v1.0.1

## Upload-only staging

The current publication preparation rebuilds the approved application with 1.0.1
version metadata, refreshes documentation/payload manifests, and rebuilds the
installer around the matching Portable.zip payload. It does not rerun application, emulator, DPI, installer
or automated test suites. Archive inventories and SHA-256 records describe the
staged files, not a new runtime certification.

Repository uploads use the clean source tree (the contents of Source.zip), not
the binary release folder. GitHub Release assets are Setup.exe, Portable.zip,
Source.zip, version.json and the accompanying release documentation/manifests.
Do not upload local validation reports, caches, engine data or temporary build
helpers. Developer audit notes are excluded from the upload source allowlist.
The owner confirmed publication version 1.0.1. The historical v1.0 release is
retained. The official Android Emulator Extended Controls built-in
D-pad remains deferred, separately from the fixed Salem DPadWidget.

## Clean build

Use 64-bit Windows and Python 3.14.4 x64. From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File build_tools\build_release.ps1
```

The script creates a fresh `.venv-release`, installs exact pinned dependencies and runs Ruff, targeted mypy, pytest and compile checks. It builds only the checked-in relative-path specs, with `console=False`, no UPX and explicit Qt/VC runtime collection. `-ReuseEnvironment` is available for iteration, not a clean release verification.

All native binaries are checked for AMD64 architecture and import closure. VC runtime dependencies must be bundled even if present on the build computer. Windows API/OS DLLs are not redistributed. Plugin/DLL origins and runtime manifests are checked at startup before importing Qt.

Builds are reproducible in toolchain and procedure, not promised byte-for-byte identical: PE timestamps, ZIP metadata and bootloader outputs may vary. Dependency versions and artifact hashes are recorded.

## Verification and outputs

The build tests the packaged GUI at 100%, 150% and 200% scaling, an extracted relocated portable copy, a missing-QtCore negative case, and a Setup-installed copy. PATH is reduced to Windows and foreign Qt plugin variables are supplied to exercise runtime isolation. These tests do **not** create a clean Windows VM.

Only after these checks pass are both `candidate/build_local/` and `candidate/release_github/` replaced. Existing public v1.0 files in the root `build_local/` and `release_github/` are never replaced. Previous candidate copies are retained temporarily under `build/release-stage/previous-*`; a failed promotion rolls back. Close candidate Salem EXEs before rebuilding. No release is published automatically.

Upload the canonical `Setup.exe`, `Portable.zip` and `Source.zip`, plus standalone `version.json`, VERSION, toolchain manifest, README, CHANGELOG, RELEASE, third-party notices, build manifest and hashes. Do not upload duplicate branded aliases.

The app and installer are version 1.0.1. Executable Windows version resources use 1.0.1.0. No signing certificate is configured; SmartScreen may warn. Optional signing uses `SALEM_SIGNTOOL` (absolute SDK signtool path) and `SALEM_SIGN_THUMBPRINT` (Windows certificate-store identity); configured signing errors fail the build. No private key/password is stored in source.

## Clean-PC release gate

Test both Setup and Portable on a Windows 10 1809+ or Windows 11 x64 PC/VM without Python, Qt, Android Studio or development tools. A `build_tools/clean_pc_smoke.ps1` command is provided. Record OS build, architecture, startup report and logs. The affected customer's original QtCore traceback is still needed to tie a specific loader error to a confirmed cause; missing files, OS incompatibility, quarantine and architecture mismatch must not be conflated.

Then test the live engine: Launch, Stop, Restart, TV Mode/restore, remote/popout, text/fallback, volume commands, diagnostics, preferences, updates and support. Audio audibility and viewport coverage require visual/listening verification, not just ADB exit codes.

## Installer behavior

Setup stages and verifies every payload SHA-256 before replacing the installed app. The existing app is renamed on the same volume and restored if promotion fails. User engine data is separate. Shortcuts use the current user's redirected Desktop/Start Menu and point directly to the EXE. Shortcut errors are reported, not ignored.

The NSIS 3.12 installer checks native architecture and Windows build before the Python setup helper runs. It registers a current-user Apps & Features uninstaller, a direct EXE Start Menu shortcut, optional desktop shortcut and an optional launch-after-install action. Uninstall removes an explicit packaged-file list, preserving unrelated files, settings and engine data. Silent install/upgrade/uninstall are exercised under an isolated `/TEST` mode that does not alter the developer's real shortcuts or registration. Actual shortcut/registry behavior remains a separate live validation gate.

Compiler acquisition is pinned to the official NSIS ZIP and SHA-256. This is an installer shell, not a new native application launcher. The build audits PE metadata/subsystems and scans source/portable files for accidental runtime data, developer paths and common credentials. This automated scan is bounded, not a guarantee about all possible secrets in binary data.
