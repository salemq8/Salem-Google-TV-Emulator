# Salem Google TV Emulator v1.0

A Windows launcher and remote for the official Android Emulator running Google TV.
Salem is the product owner. This is an independent application, not an official Google product.
The custom Salem icon is not a Google logo.

## Install and use

- Candidate target: Windows 10 version 1809 or later (64-bit), or Windows 11; a supported x64 CPU and hardware virtualization are required. This is the runtime floor, not completed clean-machine certification. Windows 7/8/8.1 and ARM64 are not supported.
- Run `Setup.exe` for a per-user installation and Start Menu shortcut. A desktop shortcut is optional. Close Salem before upgrading.
- Alternatively extract **all** of `Portable.zip` and open `Salem Google TV Emulator.exe` inside its folder. Do not move the EXE out of that folder.
- Python, Java and Android Studio are not required on the user's PC. The app bundles its own Python/Qt runtime; Engine Setup installs portable Java and official Android tools after confirmation.
- On Overview, launch Google TV. If the engine is missing, open Setup & repair. License acceptance and Windows feature elevation require explicit confirmation. Reboot when requested.

The emulator remains a separate official window. Closing Salem or its floating remote does not stop Google TV. Use Stop explicitly. Active TV Mode is restored before Stop, Restart, or closing Salem.

First-time setup requires at least 16 GB free for downloads, extraction and device data. It uses a fixed reviewed manifest, verifies bootstrap checksums, logs each operation and revalidates existing components on retry. Failed package repairs roll back. Windows feature changes prompt for administrator approval and setup pauses until reboot.

This is a **staged upload candidate**. Version remains 1.0 until the owner confirms the publication version; public version 1.0 has not been replaced. Packaging does not imply new runtime testing or clean-machine certification.

The candidate includes strict portable Microsoft JDK validation, shared generation-scoped remote/session handling with a bounded ordered queue, and Salem's geometric D-pad hitboxes. Existing healthy pinned JDK installations are reused.

## Controls

Overview provides Launch, Stop, Restart, TV Mode, Remote, Pop-out Remote, repair and APK installation.
Remote & input has the shared D-pad, Back/Home/Menu, volume/mute, text input and Test Sound.
The entire Salem D-pad circle is interactive: the center selects OK and the outer ring selects a direction. Hover and pressed feedback use the same geometry, with one command per press.
F11 toggles TV Mode while Salem is focused. Arrow keys, Enter, Escape/Backspace and Home send remote actions except when editing a field.

Text uses the existing ADB input, clipboard and per-character fallbacks. Arabic/Unicode support depends on the installed image's clipboard command and focused input method. Failures are displayed; command success alone cannot prove a TV app accepted the text.
Test Sound sets media volume to 10; it does not synthesize a sound. Audible verification requires playing content in the TV app.

TV Mode preserves the existing Win32 borderless implementation. Outer-window coverage does not prove the internal Qt viewport fills the screen. The emulator toolbar can remain; candidate geometry and child hierarchy are reported without claiming a render surface was conclusively identified.

Deferred: the official Android Emulator Extended Controls built-in D-pad is separate from Salem Remote and remains deferred for later investigation.

## Preferences, updates and support

Dark, Light and System themes, log retention, startup update checks and floating-remote topmost preferences are saved atomically. The interface is English; Arabic text entry is supported subject to the engine limitations above. Old language preferences are retained in data, but the previous untranslated language selector is no longer offered.

Update checks read `version.json` from the latest public GitHub Release assets of `salemq8/Salem-Google-TV-Emulator`. They never automatically execute downloads. HTTP errors, missing assets and invalid metadata are reported honestly. Support opens an email draft to `1salembot.support@gmail.com`; nothing is sent automatically.

## Data and diagnostics

- Engine/JDK: `C:\Users\Public\SalemTVBox\AndroidSDK` and `JDK21`.
- Emulator log: `C:\Users\Public\SalemTVBox\logs\emulator.log`.
- Application and startup logs: `%LOCALAPPDATA%\Salem Google TV Emulator\logs`.
- Preferences: `%APPDATA%\Salem Google TV Emulator\settings.json`.
- AVDs remain in the existing Android AVD location. Reinstallation does not remove engine data or preferences.

Diagnostics separates runtime snapshots, activity and setup output. Rotating `app.log`, `setup.log`, `update.log` and `crash.log` are stored in the application logs folder. Review diagnostic text before sharing; redaction is best-effort and reports can include local paths, device state and entered text.
An incomplete installation produces an actionable native Windows error even if Qt cannot load.

## Development

Build-machine prerequisite only: Python **3.14.4 x64** with the `py` launcher.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -m pytest
```

`run.bat` is development-only. Releases and shortcuts launch the EXE directly.
See [Architecture](docs/ARCHITECTURE.md), [Build and release](RELEASE.md) and [Third-party notices](THIRD_PARTY_NOTICES.md).

The local packaged Windows smoke tests are distinct from certification on a clean Windows PC. Do not infer clean-PC/customer-crash verification from a developer-machine pass.
