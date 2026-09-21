import json

from build_tools.bundle import copy_notices, sha256, write_manifests


def test_notice_copy_excludes_runtime_code_and_bytecode(tmp_path):
    copy_notices(tmp_path)
    files = list((tmp_path / "licenses").rglob("*"))
    assert any(path.is_file() for path in files)
    assert not any(path.suffix in (".py", ".pyc") or "__pycache__" in path.parts for path in files)


def test_runtime_and_payload_manifests_are_idempotent(tmp_path):
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "sample.dll").write_bytes(b"binary")
    write_manifests(tmp_path)
    first = (tmp_path / "payload-manifest.json").read_bytes()
    write_manifests(tmp_path)
    assert (tmp_path / "payload-manifest.json").read_bytes() == first
    payload = json.loads(first)
    assert "payload-manifest.json" not in payload
    assert all(sha256(tmp_path / path) == digest for path, digest in payload.items())
