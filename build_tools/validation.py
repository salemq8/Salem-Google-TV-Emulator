"""Candidate release gates: identities, sensitive files and optional Windows signing."""
from __future__ import annotations

import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

import pefile


def verify_metadata(executable: Path, version: str) -> dict:
    with pefile.PE(str(executable), fast_load=False) as pe:
        strings = {}
        for group in getattr(pe, "FileInfo", []):
            for entry in group:
                for table in getattr(entry, "StringTable", []):
                    strings.update({k.decode(): v.decode() for k, v in table.entries.items()})
        expected = version.split(".")
        actual = strings.get("ProductVersion", "").split(".")
        if (strings.get("ProductName") != "Salem Google TV Emulator"
                or actual + ["0"] * (4 - len(actual)) != expected + ["0"] * (4 - len(expected))):
            raise RuntimeError(f"Incorrect product metadata in {executable.name}: {strings}")
        if pe.OPTIONAL_HEADER.Subsystem != 2:
            raise RuntimeError(f"Console subsystem in {executable.name}")
        return strings


def privacy_scan(source: Path, portable: Path) -> dict:
    findings = []
    checked = 0
    private = {".git", "__pycache__", ".venv", ".venv-build", ".venv-release", "logs", "validation", "release_screenshots"}
    for archive_path in (source, portable):
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                parts = Path(info.filename).parts
                if any(part.lower() in private for part in parts) or Path(info.filename).name.lower() in ("settings.json", ".env", "adbkey", "adbkey.pub"):
                    findings.append(f"{archive_path.name}: private path {info.filename}")
                if Path(info.filename).suffix.lower() in (".py", ".md", ".json", ".ps1", ".spec", ".nsi", ".toml", ".txt") and info.file_size < 2_000_000:
                    text = archive.read(info).decode("utf-8", errors="replace")
                    checked += 1
                    if re.search(r"(?i)[c-z]:[\\/]Users[\\/](?!Public\b|Default\b|\{)[^\\/\s\"']+[\\/]", text):
                        findings.append(f"{archive_path.name}: personal path {info.filename}")
                    if re.search(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |EC )?PRIVATE KEY-----)", text):
                        findings.append(f"{archive_path.name}: possible credential {info.filename}")
    if findings:
        raise RuntimeError("Release privacy scan failed: " + json.dumps(findings))
    return {"text_files_checked": checked, "findings": findings, "scope": "Allowlisted source and portable paths/text; not a guarantee that arbitrary binary payloads contain no private data."}


def sign_optional(executable: Path) -> bool:
    thumbprint = os.environ.get("SALEM_SIGN_THUMBPRINT", "")
    if not thumbprint:
        return False
    tool = os.environ.get("SALEM_SIGNTOOL", "")
    if not tool or not re.fullmatch(r"[A-Fa-f0-9]{40}", thumbprint):
        raise RuntimeError("Signing configured incompletely; set SALEM_SIGNTOOL and the certificate store SHA1 thumbprint.")
    subprocess.run([tool, "sign", "/sha1", thumbprint, "/fd", "SHA256", "/tr", "http://timestamp.digicert.com", "/td", "SHA256", str(executable)], check=True, timeout=120)
    subprocess.run([tool, "verify", "/pa", str(executable)], check=True, timeout=30)
    return True
