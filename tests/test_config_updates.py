import json
from urllib.error import HTTPError

import pytest

from salem_tv_box_emulator.config import Settings, SettingsStore, SUPPORT_EMAIL
from salem_tv_box_emulator.services import updates


def test_settings_validated():
    settings = Settings.parse({"theme": "invalid", "auto_update": "false", "log_retention_days": -1,
                               "support_email": "support@salemgtv.com", "remote_always_on_top": True})
    assert settings.theme == "Dark"
    assert settings.auto_update is False
    assert settings.log_retention_days == 1
    assert settings.remote_always_on_top is True
    assert settings.support_email == SUPPORT_EMAIL


def test_settings_save_load_reset(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    settings = Settings(theme="Light", remote_always_on_top=True)
    store.save(settings)
    assert store.load() == settings
    assert store.reset() == Settings()
    assert store.load() == Settings()


def test_corrupt_settings_preserved(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("invalid", encoding="utf-8")
    store = SettingsStore(path)
    assert store.load() == Settings()
    assert store.warning
    assert path.read_text() == "invalid"


def test_atomic_save_failure_preserves_existing(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings())
    original = store.path.read_bytes()
    def fail(*args):
        raise PermissionError("locked")
    monkeypatch.setattr("salem_tv_box_emulator.config.os.replace", fail)
    with pytest.raises(PermissionError):
        store.save(Settings(theme="Light"))
    assert store.path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("version,newer", [("1.0", False), ("0.9", False), ("1.10", True), ("2.0rc1", True)])
def test_update_version_comparison(monkeypatch, version, newer):
    seen = []
    def read(url):
        seen.append(url)
        return {"version": version} if url.endswith("version.json") else {
            "assets": [{"name": "version.json", "browser_download_url": "https://example.test/version.json"}]}
    monkeypatch.setattr(updates, "read_json", read)
    result = updates.check_for_updates()
    assert result.newer is newer
    assert len(seen) == 2


@pytest.mark.parametrize("release", [{}, {"assets": []}, {"assets": [{"name": "other.json"}]}])
def test_missing_update_asset_honest(monkeypatch, release):
    monkeypatch.setattr(updates, "read_json", lambda url: release)
    with pytest.raises(ValueError):
        updates.check_for_updates()


def test_https_required():
    with pytest.raises(ValueError, match="HTTPS"):
        updates.read_json("http://example.test/version.json")


@pytest.mark.parametrize("status", [404, 403, 429, 500])
def test_update_http_errors(monkeypatch, status):
    def fail(*args, **kwargs):
        raise HTTPError("https://example.test", status, "error", {}, None)
    monkeypatch.setattr(updates, "urlopen", fail)
    with pytest.raises(RuntimeError):
        updates.read_json("https://example.test")


def test_release_version_matches():
    from pathlib import Path
    from salem_tv_box_emulator import __version__
    root = Path(__file__).resolve().parents[1]
    assert __version__ == (root / "VERSION").read_text().strip() == json.loads((root / "version.json").read_text())["version"] == "1.0"
