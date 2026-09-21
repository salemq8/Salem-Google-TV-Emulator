# Architecture

`main.py` and the module entry point reach `startup.py` before importing Qt. The startup boundary configures rotating logs, validates the frozen runtime manifest, isolates DLL/plugin search paths and reports native errors independently of Qt. `--self-test report.json` is a no-engine packaged startup/render smoke test.

`app.py` only bootstraps QApplication and `ui/window.py`. The window coordinates cached engine state, action availability and lifecycle. Views are in `ui/pages.py`, `ui/management.py` and `ui/components.py`. Setup and preferences/update/support orchestration have dedicated UI controllers. `RemotePad` is shared by the main and floating remote.

`services/tasks.py` queues engine operations in order on one worker and uses a separate small background pool for independent work. Completion/errors return through Qt signals. Duplicate polling/check tasks are coalesced; intentional remote presses remain ordered. Widgets are only read/written on the UI thread. Shutdown ignores late callbacks and never implicitly stops the emulator.

Remote input accepts at most 16 outstanding key commands, shared by the main and floating remote. Additional presses are rejected with a visible busy message, never silently reordered or replayed. Lifecycle commands do not share that input limit: Stop/Restart can still invalidate pending input and shut down the verified session.

`ui/dpad.py` supplies the single geometric DPadWidget shared by both RemotePad instances. Painting and mouse feedback use a dynamic circle; center clicks emit OK and the outer ring is partitioned by dominant axis with vertical diagonal ties. Dispatch occurs on left press only. It forwards existing key names without changing RemoteService or Android keyevent mappings.

`config.py` owns product endpoints, paths and validated atomic preferences. `services/updates.py` fetches bounded HTTPS JSON, selects the latest release's version.json asset and compares semantic versions. `services/diagnostics.py` formats read-only snapshots and does not treat candidate child geometry as proof of rendered coverage. `services/tv_mode.py` preserves window restoration state until restore succeeds.

`android_backend.py` retains the working official emulator process command and text/audio algorithms. `services/session.py` owns the only active serial, generation, AVD identity and boot state. A binder positively correlates new ready transports to `Salem_Google_TV`; it never falls back to the first emulator. Disconnect, restart and stop invalidate queued input. Both remote surfaces and text/audio use one RemoteService. Failed input is not automatically replayed because a timeout does not prove it was not delivered.

`setup_wizard.py` is the public setup facade and progress/result contract. `services/setup_engine.py` runs validated, resumable stages; `toolchain.py` verifies downloads and safely extracts/rolls back; `package_manager.py` isolates the current Android CLI and pinned sdkmanager compatibility backend. `toolchain_manifest.json` records exact candidate revisions/hashes. Existing AVD data is preserved if incompatible rather than silently erased.

`services/java_runtime.py` validates the pinned Microsoft runtime against parsed release metadata and successful java version output, including stderr, while preserving x64/vendor/full-version checks. A healthy portable JDK is reused rather than downloaded again.

`services/engine_setup.py` checks virtualization before downloads, persists reboot requirements, and returns a distinct restart-needed result. `windows_features.py` runs hidden elevated Windows feature checks only after UI consent. `windows_embed.py` retains window discovery/borderless/restoration, with same-process title enumeration excluded to prevent a worker/UI shutdown deadlock. The working launch flags remain CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP, without DETACHED_PROCESS.

`build_tools/` owns specs, pinned-build orchestration, PE dependency audits, manifests, installer and smoke validation. No runtime application module imports packaging orchestration. `tests/` covers settings, updates, backend contracts, view wiring, command ordering, lifecycle and installer integrity/rollback.

NSIS supplies the install/uninstall UI and the pre-Python OS/architecture gate. An embedded windowed helper verifies and stages the application payload before replacement. This does not change the application's EXE entry path. Candidate outputs are isolated under `candidate/`; publication and public version changes require Salem's approval.

## Removed debt

The previous approximately 2,600-line UI/controller module has been replaced with focused views/services. Duplicated remotes, unreachable docking UI, generic catch-and-ignore task results, synchronous UI SDK/ADB work, destructive diagnostic refreshes, fake language selection, unconditional update inequality and machine-specific generated specs are removed. Working backend logic remains behind explicit boundaries instead of being reimplemented.

The audit and baseline archive under local `validation/` document the pre-rework state. Validation, engine logs, personal settings and cached artifacts are excluded from Source.zip by an allowlist.
