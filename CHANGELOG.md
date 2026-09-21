# Salem Google TV Emulator Changelog

## v1.0 - 2026-06-11

- Released Salem Google TV Emulator v1.0 as a Google TV focused Windows launcher.
- Renamed the Windows product identity to Salem Google TV Emulator.
- Removed previous dual-system product paths, UI choices, setup stages, package selection, and release documentation.
- Kept the official Android Emulator backend and the working `Salem_Google_TV` launch flow.
- Kept dynamic ADB serial detection for `emulator-XXXX` devices.
- Kept remote controls, pop-out remote, Send Text to TV, audio buttons, diagnostics, and TV Mode.
- Added safe Google TV AVD performance controls for RAM, CPU cores, GPU host mode, and valid network latency/speed settings.
- Added network status diagnostics without claiming artificial network acceleration.
- Added v1.0 release metadata, README, version file, changelog, portable package output, source package output, and installer build tooling.
- Added a complete release UI with Home, Remote, Text Input, Audio, TV Mode, Network & Performance, Diagnostics, Settings, Updates, Setup / Repair, Support, and About pages.
- Added AppUserModelID, in-app logo/header branding, local-only settings, latest GitHub Release `version.json` update checks, mailto support draft, and privacy-safe release package scan.
- Set the support contact to `1salembot.support@gmail.com`.
## Unreleased Engineering Candidate - rework-2026-09-19

- Upload staging retains version 1.0 pending the owner's version confirmation; no public release is replaced automatically.
- Fixed pinned Microsoft OpenJDK validation using full runtime/build version parsing, valid x64 executable checks, Microsoft metadata and successful command status, including version output on stderr. Healthy installations are reused.
- Preserved positive AVD/session binding, ordered remote dispatch, the 16-command bound and stale-generation rejection across stop/reconnect/restart.
- Replaced Salem Remote's rectangular D-pad buttons with a single geometric DPadWidget: circular OK, gap-free directional ring, shared hover/pressed hit-testing and one command per press, scaled from current widget dimensions.
- Deferred the official Android Emulator Extended Controls built-in D-pad for later investigation; it is not part of Salem Remote.
- Replaced the monolithic interface with a coherent sidebar UI, shared remote, focused services and ordered background operations.
- Added validated atomic preferences, honest update errors/version comparison, actionable text failures and persistent activity diagnostics.
- Added a standard-library startup boundary, runtime manifest validation, bundled Qt/VC dependency checks, pinned clean builds and relocated/DPI/installed smoke tests.
- Installer now verifies staged payloads before replacement and reports shortcut failures. Version remains 1.0.
- Customer-specific QtCore root cause and clean-PC certification remain separate verification gates; see RELEASE.md.
- Introduced a generation-scoped emulator session shared by remote, text and audio, with positive AVD correlation and rejection of stale queued commands after restart/reconnection.
- Replaced mutable SDK acquisition with a pinned candidate toolchain, verified downloads, logged command/exit results, explicit Android CLI capability detection and pinned compatibility fallback.
- Added staged package repair/rollback, durable setup failure details and a virtualization/reboot preflight.
- Added a native installer OS check, optional desktop shortcut, uninstall registration, safe explicit-file uninstall, metadata checks and candidate-only output promotion.
- Public v1.0 remains unchanged; candidate tooling and clean-machine/live-engine behavior are not yet certified.
