# Salem Google TV Emulator v1.0

Salem Google TV Emulator is a Windows 10/11 desktop product for launching and controlling Google TV through Google's official Android Emulator.

Salem does not build an emulator from scratch. It installs and manages the official Android SDK command-line tools, creates the `Salem_Google_TV` AVD, launches `emulator.exe`, detects the active ADB serial, and gives normal users a polished TV-style launcher.

## Product Focus

- Google TV only.
- One clear launch path: Launch Google TV.
- Premium dark Windows dashboard with left navigation.
- Custom Salem TV/remote icon artwork. It does not use official Google logo assets.
- No Android Studio requirement when Salem's setup wizard can install the command-line tools.
- Android Studio remains optional for manual SDK management.

## Main Screens

- Home: product header, Google TV status, launch controls, TV Mode shortcuts, quick ADB/window/audio/network status, logs, and diagnostics.
- Remote: circular D-pad, OK, Back, Home, Menu, volume, mute, Power/Stop, and pop-out remote.
- Text Input: Send Text to TV with English, Arabic, numbers, symbols, and fallback input paths.
- Audio: Volume Up, Volume Down, Mute, Test Sound, and audio diagnostics.
- TV Mode: Enter/Exit TV Mode, F11 hint, selected emulator window, and viewport fill diagnostics.
- Network & Performance: read-only network diagnostics and safe AVD RAM/CPU/GPU settings.
- Diagnostics: copy diagnostics, open logs, latest emulator log, ADB output, adb devices, launch command, PID, active serial, TV Mode candidates, and window hierarchy.
- Settings: theme, language placeholder, auto update, log retention, local settings save/reset, and log cleanup.
- Updates: current version, manual update check, auto update checkbox, and honest GitHub Releases `version.json` skeleton.
- Setup / Repair: Install Google TV Engine, Retry Setup, Refresh, Install APK, setup progress, and manual Google TV package override.
- Support: support email, open logs, copy diagnostic info, mailto draft, and Discord placeholder.
- About: version, product identity, official Android Emulator backend note, and custom icon/legal note.

## Core Features

- Launch Google TV, Stop Google TV, Restart Google TV, and Fix Everything & Launch.
- One-button Install Google TV Engine setup wizard.
- Portable Microsoft OpenJDK 21 installed into `C:\Users\Public\SalemTVBox\JDK21`.
- Android SDK tools installed into `C:\Users\Public\SalemTVBox\AndroidSDK`.
- Google TV system-image detection from `sdkmanager --list`.
- Automatic `Salem_Google_TV` AVD creation.
- Automatic HypervisorPlatform and VirtualMachinePlatform checks with restart warning when Windows features change.
- Dynamic ADB serial detection for `emulator-XXXX` devices.
- On-screen remote and pop-out remote titled `Salem Remote`.
- Keyboard shortcuts for D-pad, OK, Back, Home, and F11 TV Mode.
- Send Text to TV with direct ADB input, clipboard paste fallback, and character-by-character fallback.
- Audio controls: Volume Up, Volume Down, Mute, and Test Sound.
- Safe performance controls for Google TV AVD RAM, CPU cores, GPU host mode, and network diagnostics.

## Run From Source

```bat
run.bat
```

Or manually:

```bat
py -3 -m pip install -r requirements.txt
py -3 -m salem_tv_box_emulator
```

## Automatic Setup

1. Run Salem.
2. Press Install Google TV Engine.
3. Confirm SDK license acceptance when prompted.
4. Wait for setup stages to complete.
5. Press Launch Google TV.

If automatic package detection fails, open Setup / Repair, paste a full Google TV system-image package path into Manual Google TV Package, and press Retry Setup.

## Launch And Control

Salem launches the official emulator window with this shape:

```text
C:\Users\Public\SalemTVBox\AndroidSDK\emulator\emulator.exe -avd Salem_Google_TV -no-metrics
```

The app starts the emulator with `subprocess.Popen`, keeps the process reference alive, and writes emulator output to:

```text
C:\Users\Public\SalemTVBox\logs\emulator.log
```

After launch, Salem polls `adb devices -l` until an `emulator-XXXX` device appears as `device`. The detected serial is stored and used for remote, text, audio, APK, and diagnostics commands.

## TV Mode

TV Mode is a Windows borderless fullscreen mode for the official emulator window. Salem finds the main `Android Emulator - Salem_Google_TV` window, ignores Extended Controls, saves the original style and rectangle, removes the title bar and borders, moves the window to the monitor bounds, and restores the original window when TV Mode exits.

The official emulator toolbar may remain visible depending on emulator settings. Salem v1.0 reports viewport and child-window diagnostics instead of guessing hidden emulator internals.

## Updates

The Updates page is wired for a GitHub Releases `version.json` feed. If no update feed URL is configured, manual checks report `not configured yet` instead of showing fake download states.

## Release Artifacts

The v1.0 release build creates:

- `release_github\Setup.exe`
- `release_github\Portable.zip`
- `release_github\Source.zip`
- `release_github\Salem_Google_TV_Emulator_Setup_v1.0.exe`
- `release_github\Salem_Google_TV_Emulator_Portable_v1.0.zip`
- `release_github\Salem_Google_TV_Emulator-v1.0-source.zip`
- `release_github\version.json`
- `release_github\README.md`
- `release_github\CHANGELOG.md`
- `release_github\RELEASE.md`
- `release_github\RELEASE_CHECKLIST.md`

Build command:

```powershell
.\build_tools\build_release.ps1
```

PyInstaller is used for EXE generation, app icon embedding, and version metadata.
