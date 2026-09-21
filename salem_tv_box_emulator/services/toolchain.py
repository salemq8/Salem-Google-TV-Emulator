"""Strict reviewed bootstrap manifest, verified resumable downloads and staged extraction."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..config import resource_path
from .errors import SalemError


@dataclass(frozen=True)
class Artifact:
    version: str
    url: str
    digest: str
    algorithm: str

    @classmethod
    def parse(cls, value: dict) -> Artifact:
        algorithm = value.get("algorithm", "sha256")
        digest = value["digest"].lower()
        if algorithm not in ("sha256", "sha1") or len(digest) != (64 if algorithm == "sha256" else 40) or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid artifact checksum")
        url = value["url"]
        if urlsplit(url).scheme != "https" or urlsplit(url).hostname not in ("dl.google.com", "aka.ms", "download.visualstudio.microsoft.com"):
            raise ValueError("Tool artifacts must use official HTTPS download hosts")
        return cls(value["version"], url, digest, algorithm)


def load_manifest(path: Path | None = None) -> dict:
    manifest = json.loads((path or resource_path("toolchain_manifest.json")).read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest["image"]["abi"] not in ("x86", "x86_64"):
        raise ValueError("Unsupported toolchain manifest")
    for name in ("jdk", "commandline_tools", "android_cli"):
        Artifact.parse(manifest[name])
    for package, version in manifest["packages"].items():
        if "latest" in package or not version or not all(part.isdigit() for part in version.split(".")):
            raise ValueError("Every SDK package must have a fixed revision")
    return manifest


def checksum(path: Path, algorithm: str) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def download(artifact: Artifact, cache: Path, progress) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    filename = Path(urlsplit(artifact.url).path).name
    target = cache / f"{artifact.digest[:16]}-{filename}"
    if target.exists() and checksum(target, artifact.algorithm) == artifact.digest:
        return target
    part = target.with_suffix(target.suffix + ".part")
    if part.exists() and checksum(part, artifact.algorithm) == artifact.digest:
        os.replace(part, target)
        return target
    offset = part.stat().st_size if part.exists() else 0
    request = urllib.request.Request(artifact.url, headers={"Range": f"bytes={offset}-"} if offset else {})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if urlsplit(response.url).scheme != "https":
                raise SalemError("DownloadRejected", "The download was redirected to an insecure address.")
            append = response.status == 206 and offset > 0
            done = offset if append else 0
            length = int(response.headers.get("Content-Length", "0"))
            total = done + length if length else 0
            with part.open("ab" if append else "wb") as stream:
                while block := response.read(1024 * 1024):
                    stream.write(block)
                    done += len(block)
                    progress(done, total)
                stream.flush()
                os.fsync(stream.fileno())
        if checksum(part, artifact.algorithm) != artifact.digest:
            part.unlink(missing_ok=True)
            raise SalemError("ChecksumMismatch", "Downloaded tools failed verification. Retry the failed step; no unverified files were installed.")
        os.replace(part, target)
        return target
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and offset:
            part.unlink(missing_ok=True)
            return download(artifact, cache, progress)
        raise SalemError("DownloadFailed", f"Tool download failed (HTTP {exc.code}). Check your connection and retry.", str(exc)) from exc
    except (OSError, TimeoutError) as exc:
        raise SalemError("DownloadFailed", "Tool download was interrupted. Check your connection and retry; partial data is retained.", str(exc)) from exc


def install_zip(archive: Path, destination: Path, root_name: str | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".salem-extract-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        with zipfile.ZipFile(archive) as zipped:
            for info in zipped.infolist():
                if not (stage / info.filename).resolve().is_relative_to(stage.resolve()):
                    raise SalemError("ArchiveRejected", "Unsafe path in downloaded archive.")
            zipped.extractall(stage)
        roots = [p for p in stage.iterdir() if p.is_dir()]
        payload = stage / root_name if root_name else (roots[0] if len(roots) == 1 else None)
        if payload is None or not payload.is_dir():
            raise SalemError("ArchiveRejected", "Downloaded archive has an unexpected layout.")
        backup = stage / ".previous"
        if destination.exists():
            destination.rename(backup)
        try:
            payload.rename(destination)
        except OSError:
            if backup.exists():
                backup.rename(destination)
            raise


def require_disk(path: Path, required: int) -> None:
    probe = path.resolve()
    while not probe.exists():
        probe = probe.parent
    available = shutil.disk_usage(probe).free
    if available < required:
        raise SalemError("InsufficientDisk", f"Not enough disk space. Required: {required / 2**30:.1f} GB; available: {available / 2**30:.1f} GB.")
