from types import SimpleNamespace
from unittest.mock import Mock

from salem_tv_box_emulator.services import engine_setup


def test_pending_reboot_does_not_install_or_enable_again(monkeypatch):
    monkeypatch.setattr(engine_setup, "pending_reboot", lambda: True)
    install, enable = Mock(), Mock()
    monkeypatch.setattr(engine_setup, "install_tv_emulator_engine", install)
    monkeypatch.setattr(engine_setup, "check_and_enable_hypervisor_features_elevated", enable)
    result = engine_setup.repair_engine("", Mock())
    assert result.restart_required and result.setup is None
    install.assert_not_called()
    enable.assert_not_called()


def test_feature_change_stops_before_downloads(monkeypatch):
    monkeypatch.setattr(engine_setup, "pending_reboot", lambda: False)
    status = SimpleNamespace(ready=False, missing=["HypervisorPlatform"], to_text=lambda: "pending")
    monkeypatch.setattr(engine_setup, "check_hypervisor_features", lambda: status)
    monkeypatch.setattr(engine_setup, "check_and_enable_hypervisor_features_elevated", lambda _: SimpleNamespace(status=status, restart_required=True))
    install, save = Mock(), Mock()
    monkeypatch.setattr(engine_setup, "install_tv_emulator_engine", install)
    monkeypatch.setattr(engine_setup, "save_pending_fix_launch", save)
    assert engine_setup.repair_engine("", Mock()).restart_required
    install.assert_not_called()
    save.assert_called_once_with("google_tv")


def test_ready_features_proceed_without_elevation(monkeypatch):
    monkeypatch.setattr(engine_setup, "pending_reboot", lambda: False)
    status = SimpleNamespace(ready=True, to_text=lambda: "ready")
    monkeypatch.setattr(engine_setup, "check_hypervisor_features", lambda: status)
    enable, clear, install = Mock(), Mock(), Mock(return_value="setup")
    monkeypatch.setattr(engine_setup, "check_and_enable_hypervisor_features_elevated", enable)
    monkeypatch.setattr(engine_setup, "clear_pending_fix_launch", clear)
    monkeypatch.setattr(engine_setup, "install_tv_emulator_engine", install)
    result = engine_setup.repair_engine("", Mock())
    assert result.setup == "setup" and not result.restart_required
    enable.assert_not_called()
