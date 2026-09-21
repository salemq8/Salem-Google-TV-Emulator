"""Repair workflow shared by the UI and tests; installation stays in setup_wizard."""
from dataclasses import dataclass

from ..setup_wizard import ProgressCallback, SetupProgress, SetupResult, install_tv_emulator_engine
from ..windows_features import (
    check_and_enable_hypervisor_features_elevated,
    check_hypervisor_features,
    clear_pending_fix_launch,
    save_pending_fix_launch,
    pending_reboot,
)


@dataclass(frozen=True)
class RepairResult:
    setup: SetupResult | None
    hypervisor: str
    restart_required: bool


def repair_engine(manual_package: str, progress: ProgressCallback) -> RepairResult:
    progress(SetupProgress("Preflight", "active", "Checking Windows virtualization features..."))
    if pending_reboot():
        return RepairResult(None, "Windows restart is still required.", True)
    status = check_hypervisor_features()
    restart = False
    if not status.ready:
        result = check_and_enable_hypervisor_features_elevated(status.missing)
        status, restart = result.status, result.restart_required
        if not status.ready and not restart:
            raise RuntimeError(f"Windows virtualization is not ready. {status.to_text()}")
    if restart:
        save_pending_fix_launch("google_tv")
        return RepairResult(None, status.to_text(), True)
    else:
        clear_pending_fix_launch()
    setup = install_tv_emulator_engine(True, progress, manual_package)
    return RepairResult(setup, status.to_text(), restart)
