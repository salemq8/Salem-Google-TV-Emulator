"""Reviewed native installer compiler; no global NSIS installation required."""
from __future__ import annotations

import hashlib
import subprocess
import urllib.request
import zipfile
from pathlib import Path

VERSION = "3.12"
DIGEST = "56581f90db321581c5381193d796fffcf2d24b2f8fed2160a6c6a3baa67f2c4f"
URL = "https://downloads.sourceforge.net/project/nsis/NSIS%203/3.12/nsis-3.12.zip"


def compiler(root: Path) -> Path:
    cache = root / "build/installer-toolchain"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"nsis-{VERSION}.zip"
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != DIGEST:
        request = urllib.request.Request(URL, headers={"User-Agent": "Wget/1.21.4"})
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read(8 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != DIGEST:
            raise RuntimeError("NSIS compiler download did not match its reviewed official checksum.")
        archive.write_bytes(data)
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            if not (cache / item.filename).resolve().is_relative_to(cache.resolve()):
                raise RuntimeError("Unsafe compiler archive entry.")
        zipped.extractall(cache)
    return cache / f"nsis-{VERSION}/makensis.exe"


def build(root: Path, stage: Path, app: Path) -> Path:
    # A generated explicit delete list prevents recursive removal of user-created data.
    lines = []
    for path in sorted(app.rglob("*")):
        if path.is_file():
            relative = str(path.relative_to(app.parent)).replace("$", "$$")
            lines.append(f'Delete "$INSTDIR\\{relative}"')
    for path in sorted([app, *[p for p in app.rglob("*") if p.is_dir()]], key=lambda p: len(p.parts), reverse=True):
        relative = str(path.relative_to(app.parent)).replace("$", "$$")
        lines.append(f'RMDir "$INSTDIR\\{relative}"')
    (stage / "uninstall-files.nsh").write_text("\n".join(lines), encoding="utf-8")
    subprocess.run([str(compiler(root)), "/V2", f"/DROOT={root}", f"/DSTAGE={stage}", str(root / "build_tools/installer.nsi")],
                   check=True, timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
    return stage / "dist/Setup.exe"
