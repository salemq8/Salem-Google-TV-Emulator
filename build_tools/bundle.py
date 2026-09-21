"""Collect supported wheel binaries and audit the actual PE dependency graph."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import shutil
from pathlib import Path

import pefile

QT_REQUIRED = ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "pyside6.abi3.dll")
VC_REQUIRED = ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def qt_binaries() -> list[tuple[str, str]]:
    import PySide6
    import shiboken6
    qt = Path(PySide6.__file__).parent
    shiboken = Path(shiboken6.__file__).parent
    files = [(qt / name, "PySide6") for name in QT_REQUIRED]
    files += [(qt / name, ".") for name in VC_REQUIRED]
    files += [(shiboken / "shiboken6.abi3.dll", "shiboken6")]
    files += [(qt / "plugins/platforms/qwindows.dll", "PySide6/plugins/platforms")]
    for file, _ in files:
        if not file.is_file():
            raise RuntimeError(f"Pinned wheel is incomplete: {file}")
    return [(str(file), dest) for file, dest in files]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_binary_closure(app: Path) -> dict:
    root = app / "_internal"
    files = list(root.rglob("*.dll")) + list(root.rglob("*.pyd")) + list(app.glob("*.exe"))
    names = {p.name.lower() for p in files}
    required = {n.lower() for n in (*QT_REQUIRED, *VC_REQUIRED, "QtCore.pyd", "shiboken6.abi3.dll", "python3.dll", "qwindows.dll")}
    missing = sorted(required - names)
    contaminated = [str(p.relative_to(app)) for p in files if p.name.lower() == "icuuc.dll" or p.name.lower().startswith(("api-ms-", "ext-ms-"))]
    if contaminated:
        raise RuntimeError(f"Windows OS libraries unexpectedly bundled (possible PATH contamination): {contaminated}")
    wrong_arch = []
    external = set()
    system = Path(os.environ["SystemRoot"]) / "System32"
    graph = {}
    for file in files:
        with pefile.PE(str(file), fast_load=True) as pe:
            if pe.FILE_HEADER.Machine != 0x8664:
                wrong_arch.append(str(file.relative_to(app)))
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
            imports = [entry.dll.decode().lower() for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])]
            graph[str(file.relative_to(app))] = imports
            for name in imports:
                if name not in names:
                    if name.startswith(("api-ms-", "ext-ms-")) or (system / name).is_file():
                        external.add(name)
                    else:
                        missing.append(f"{file.name} -> {name}")
            for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
                name = entry.dll.decode().lower()
                dependency = next((p for p in files if p.name.lower() == name), None)
                if dependency is None:
                    continue
                with pefile.PE(str(dependency), fast_load=True, max_symbol_exports=100_000) as imported:
                    imported.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
                    exports = getattr(imported, "DIRECTORY_ENTRY_EXPORT", None)
                    symbols = {symbol.name for symbol in exports.symbols} if exports else set()
                missing.extend(f"{file.name} -> {name}!{symbol.name.decode(errors='replace')}" for symbol in entry.imports if symbol.name and symbol.name not in symbols)
    # VC runtimes must be shipped even if installed in System32 on the build PC.
    if missing or wrong_arch:
        raise RuntimeError(f"Bundle dependency validation failed ({len(missing)} unresolved imports). Missing={missing[:30]}; wrong architecture={wrong_arch}")
    return {"binaries": len(files), "machine": "AMD64", "os_dependencies": sorted(external), "imports": graph}


def write_manifests(app: Path) -> None:
    root = app / "_internal"
    files = {p.relative_to(root).as_posix(): p.stat().st_size for p in sorted(root.rglob("*")) if p.is_file() and p.name != "runtime-manifest.json"}
    (root / "runtime-manifest.json").write_text(json.dumps({"files": files}, indent=2), encoding="utf-8")
    hashes = {p.relative_to(app).as_posix(): sha256(p) for p in sorted(app.rglob("*")) if p.is_file() and p != app / "payload-manifest.json"}
    (app / "payload-manifest.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")


def copy_notices(app: Path) -> None:
    folder = app / "licenses"
    folder.mkdir()
    for name in ("PySide6-Essentials", "shiboken6", "packaging", "pyinstaller"):
        dist = importlib.metadata.distribution(name)
        for file in dist.files or []:
            is_notice = file.name.lower().startswith(("license", "copying", "notice"))
            is_metadata_license = any(part.endswith(".dist-info") for part in file.parts) and "licenses" in file.parts
            if (is_notice or is_metadata_license) and "__pycache__" not in file.parts and file.suffix != ".pyc":
                source = Path(dist.locate_file(file))
                if source.is_file():
                    dest = folder / name / str(file)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
    import sys
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, folder / "Python-LICENSE.txt")
