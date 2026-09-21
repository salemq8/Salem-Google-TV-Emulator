import hashlib
import json
import zipfile

import pytest

from build_tools.installer import APP_NAME, extract_verified, install


def package(path, payload=b"test executable"):
    with zipfile.ZipFile(path, "w") as archive:
        name = f"{APP_NAME}.exe"
        archive.writestr(f"{APP_NAME}/{name}", payload)
        archive.writestr(f"{APP_NAME}/payload-manifest.json", json.dumps({name: hashlib.sha256(payload).hexdigest()}))


def test_install_verified_and_upgrade(tmp_path):
    archive = tmp_path / "portable.zip"
    package(archive)
    exe = install(archive, tmp_path / "installed")
    assert exe.read_bytes() == b"test executable"
    package(archive, b"new executable")
    assert install(archive, tmp_path / "installed").read_bytes() == b"new executable"


def test_bad_archive_preserves_previous(tmp_path):
    archive = tmp_path / "portable.zip"
    package(archive)
    exe = install(archive, tmp_path / "installed")
    with zipfile.ZipFile(archive, "w") as broken:
        broken.writestr(f"{APP_NAME}/payload-manifest.json", "{}")
    with pytest.raises(ValueError):
        install(archive, tmp_path / "installed")
    assert exe.read_bytes() == b"test executable"


def test_archive_traversal_rejected(tmp_path):
    archive = tmp_path / "portable.zip"
    with zipfile.ZipFile(archive, "w") as malicious:
        malicious.writestr("../../outside.txt", "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        extract_verified(archive, tmp_path / "stage")


def test_unrelated_install_folder_preserved(tmp_path):
    target = tmp_path / "unrelated"
    target.mkdir()
    (target / "personal.txt").write_text("keep")
    with pytest.raises(ValueError, match="unrelated"):
        install(tmp_path / "missing.zip", target)
    assert (target / "personal.txt").read_text() == "keep"
