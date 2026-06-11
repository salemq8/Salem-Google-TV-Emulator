from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .android_backend import CREATE_NO_WINDOW, SALEM_LOG_DIR


REQUIRED_FEATURES = ("HypervisorPlatform", "VirtualMachinePlatform")
PENDING_FIX_PATH = SALEM_LOG_DIR / "pending_fix_launch.json"
FEATURE_SCRIPT_PATH = SALEM_LOG_DIR / "enable_hypervisor_features.ps1"
FEATURE_LOG_PATH = SALEM_LOG_DIR / "enable_hypervisor_features.log"
FEATURE_STATUS_PATH = SALEM_LOG_DIR / "hypervisor_feature_status.json"


@dataclass(frozen=True)
class WindowsFeature:
    name: str
    state: str
    output: str

    @property
    def enabled(self) -> bool:
        return self.state.lower() == "enabled"

    @property
    def requires_elevation(self) -> bool:
        return "requires elevation" in self.state.lower() or "exit 740" in self.state.lower()


@dataclass(frozen=True)
class HypervisorStatus:
    features: list[WindowsFeature]

    @property
    def missing(self) -> list[str]:
        return [feature.name for feature in self.features if not feature.enabled]

    @property
    def ready(self) -> bool:
        return not self.missing

    def to_text(self) -> str:
        lines = ["Hypervisor status:"]
        for feature in self.features:
            lines.append(f"- {feature.name}: {feature.state or 'Unknown'}")
        if any(feature.requires_elevation for feature in self.features):
            lines.append("Elevated check required to confirm Windows feature state.")
        elif self.missing:
            lines.append("Restart required after enabling missing Windows features.")
        return "\n".join(lines)


@dataclass(frozen=True)
class FeatureEnableResult:
    restart_required: bool
    status: HypervisorStatus
    output: str


def check_hypervisor_features() -> HypervisorStatus:
    if sys.platform != "win32":
        return HypervisorStatus([WindowsFeature(name, "Unsupported OS", "") for name in REQUIRED_FEATURES])
    return HypervisorStatus([_check_feature(name) for name in REQUIRED_FEATURES])


def enable_hypervisor_features_elevated(feature_names: list[str]) -> str:
    if sys.platform != "win32":
        raise RuntimeError("Windows feature enablement is only available on Windows.")
    if not feature_names:
        return "No features to enable."

    SALEM_LOG_DIR.mkdir(parents=True, exist_ok=True)
    status_path_json = json.dumps(str(FEATURE_STATUS_PATH))
    features_array = "@(" + ",".join(json.dumps(name) for name in feature_names) + ")"
    commands = [
        "$ErrorActionPreference = 'Continue'",
        f"Start-Transcript -Path {json.dumps(str(FEATURE_LOG_PATH))} -Force",
        f"$features = {features_array}",
        "$changed = $false",
        "$featureResults = @()",
        "foreach ($feature in $features) {",
        "  $before = Get-WindowsOptionalFeature -Online -FeatureName $feature",
        "  if ($before.State -ne 'Enabled') {",
        "    dism.exe /online /enable-feature /featurename:$feature /all /norestart",
        "    $changed = $true",
        "  }",
        "  $after = Get-WindowsOptionalFeature -Online -FeatureName $feature",
        "  $featureResults += [pscustomobject]@{ FeatureName = $feature; State = [string]$after.State }",
        "}",
        f"[pscustomobject]@{{ Changed = $changed; Features = $featureResults }} | ConvertTo-Json -Depth 4 | Set-Content -Path {status_path_json} -Encoding UTF8",
        "Stop-Transcript",
        "Write-Host 'Windows feature check complete.'",
    ]
    FEATURE_SCRIPT_PATH.write_text("\n".join(commands), encoding="utf-8")

    escaped_script = str(FEATURE_SCRIPT_PATH).replace("'", "''")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        (
            "Start-Process powershell.exe "
            "-Verb RunAs "
            "-Wait "
            f"-ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ''{escaped_script}'''"
        ),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=900,
        creationflags=CREATE_NO_WINDOW,
        errors="replace",
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    if result.returncode != 0:
        raise RuntimeError(output or f"Feature enablement exited with code {result.returncode}.")
    return output or f"Requested enablement for: {', '.join(feature_names)}"


def check_and_enable_hypervisor_features_elevated(feature_names: list[str] | None = None) -> FeatureEnableResult:
    names = feature_names or list(REQUIRED_FEATURES)
    output = enable_hypervisor_features_elevated(names)
    status_data = _read_elevated_feature_status()
    changed = bool(status_data.get("Changed"))
    features: list[WindowsFeature] = []
    raw_features = status_data.get("Features") or []
    if isinstance(raw_features, dict):
        raw_features = [raw_features]
    for feature in raw_features:
        name = str(feature.get("FeatureName", "Unknown"))
        state = str(feature.get("State", "Unknown"))
        features.append(WindowsFeature(name, state, "Elevated check"))
    if not features:
        features = check_hypervisor_features().features
    return FeatureEnableResult(changed, HypervisorStatus(features), output)


def save_pending_fix_launch(selected_type: str) -> None:
    SALEM_LOG_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_FIX_PATH.write_text(json.dumps({"selected_type": "google_tv"}, indent=2), encoding="utf-8")


def load_pending_fix_launch() -> str | None:
    if not PENDING_FIX_PATH.exists():
        return None
    try:
        data = json.loads(PENDING_FIX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    selected_type = data.get("selected_type")
    return "google_tv" if selected_type == "google_tv" else None


def clear_pending_fix_launch() -> None:
    try:
        PENDING_FIX_PATH.unlink()
    except FileNotFoundError:
        pass


def _check_feature(name: str) -> WindowsFeature:
    result = subprocess.run(
        ["dism.exe", "/online", "/Get-FeatureInfo", f"/FeatureName:{name}"],
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=CREATE_NO_WINDOW,
        errors="replace",
    )
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    state = "Unknown"
    for line in output.splitlines():
        if "State" in line and ":" in line:
            state = line.split(":", 1)[1].strip()
            break
    if result.returncode == 740:
        state = "Requires elevation to check"
    elif result.returncode != 0 and state == "Unknown":
        state = f"Unknown (exit {result.returncode})"
    return WindowsFeature(name, state, output)


def _read_elevated_feature_status() -> dict:
    try:
        return json.loads(FEATURE_STATUS_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
