"""Explicit Android CLI and pinned legacy package-manager adapters."""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Callable

from .errors import SalemError
from .support import sanitize


class ToolRunner:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.logger = logging.getLogger("salem.setup")

    def __call__(self, command: list[str], *, timeout: int = 120, input_text: str | None = None) -> str:
        tool_name = Path(command[0]).name
        if Path(command[0]).suffix.lower() in (".bat", ".cmd"):
            command = [str(Path(self.env["SystemRoot"]) / "System32/cmd.exe"), "/d", "/c", *command]
        started = time.monotonic()
        self.logger.info("command=%s", sanitize(subprocess.list2cmdline(command)))
        try:
            result = subprocess.run(command, input=input_text, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", env=self.env, timeout=timeout,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.logger.error("duration=%.2f result=interrupted stdout=%s stderr=%s exception=%s", time.monotonic() - started,
                              sanitize(str(getattr(exc, "stdout", ""))), sanitize(str(getattr(exc, "stderr", ""))), sanitize(str(exc)))
            raise SalemError("ToolInterrupted", "The setup tool could not finish. Retry the failed step; see setup.log for details.", str(exc)) from exc
        self.logger.info("duration=%.2f exit_code=%s stdout=%s stderr=%s", time.monotonic() - started,
                         result.returncode, sanitize(result.stdout), sanitize(result.stderr))
        output = "\n".join([result.stdout.strip(), result.stderr.strip()]).strip()
        if result.returncode:
            raise SalemError("PackageOperationFailed", f"{tool_name} exited with code {result.returncode}. Open Setup Log for the exact tool error.", output[-12000:])
        return output


class AndroidPackageManager:
    def __init__(self, executable: Path, sdk: Path, run: Callable) -> None:
        self.executable, self.sdk, self.run = executable, sdk, run

    def install(self, package: str, revision: str) -> str:
        raise NotImplementedError


class AndroidCLI(AndroidPackageManager):
    name = "Android CLI"

    def command(self, *args: str) -> list[str]:
        return [str(self.executable), "--no-metrics", f"--sdk={self.sdk}", "sdk", *args]

    def probe(self) -> None:
        self.run([str(self.executable), "--no-metrics", "--version"])
        self.run(self.command("list", "--all", "platform-tools"))

    def install(self, package: str, revision: str) -> str:
        return self.run(self.command("install", f"{package.replace(';', '/')}@{revision}"),
                        timeout=7200, input_text="y\n" * 200)


class SdkManager(AndroidPackageManager):
    name = "Pinned sdkmanager 19.0 compatibility backend"

    def command(self, *args: str) -> list[str]:
        return [str(self.executable), f"--sdk_root={self.sdk}", *args]

    def probe(self) -> None:
        version = self.run([str(self.executable), "--version"])
        if "19.0" not in version:
            raise SalemError("AndroidToolsUnavailable", "The pinned sdkmanager 19.0 compatibility tool could not be validated.", version)

    def install(self, package: str, revision: str) -> str:
        # Repository revision is checked before this call and installation revalidated afterwards.
        return self.run(self.command("--install", "--channel=0", package), timeout=7200, input_text="y\n" * 200)

    def licenses(self) -> str:
        return self.run(self.command("--licenses"), timeout=600, input_text="y\n" * 200)


def select_manager(modern: AndroidCLI, legacy: SdkManager, report: Callable[[str], None]) -> AndroidPackageManager:
    try:
        modern.probe()
        report("Android CLI capabilities verified.")
        return modern
    except SalemError as exc:
        report(f"Android CLI capability check failed: {exc}. Trying the explicit pinned compatibility backend.")
        logging.getLogger("salem.setup").warning("modern backend rejected: %s %s", exc, sanitize(exc.details))
        legacy.probe()
        report("Using pinned sdkmanager 19.0 compatibility backend; no upstream auto-update.")
        return legacy
