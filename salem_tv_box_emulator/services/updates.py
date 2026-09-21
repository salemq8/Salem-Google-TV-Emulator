"""Read a release manifest; never execute downloaded code."""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

from .. import __version__
from ..config import RELEASE_API, RELEASE_URL


@dataclass(frozen=True)
class UpdateResult:
    version: str
    newer: bool
    release_url: str
    source: str


def read_json(url: str) -> dict[str, object]:
    if urlsplit(url).scheme != "https":
        raise ValueError("Update sources must use HTTPS.")
    request = Request(url, headers={"User-Agent": f"Salem-Google-TV-Emulator/{__version__}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = response.read(1024 * 1024 + 1)
    except HTTPError as exc:
        messages = {
            404: "Release or version.json unavailable. Check that a public release includes version.json.",
            403: "GitHub denied the request or its rate limit was reached. Try again later.",
            429: "GitHub rate limit reached. Try again later.",
        }
        raise RuntimeError(messages.get(exc.code, f"Update request failed (HTTP {exc.code}).")) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Unable to reach GitHub. Check your connection. {exc}") from exc
    if len(payload) > 1024 * 1024:
        raise ValueError("Release metadata is unexpectedly large.")
    result = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError("Release metadata must be a JSON object.")
    return result


def check_for_updates(api_url: str = RELEASE_API, direct_url: str = "") -> UpdateResult:
    release_url = RELEASE_URL
    source = direct_url
    if not source:
        release = read_json(api_url)
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise ValueError("GitHub release has no assets list.")
        asset = next((a for a in assets if isinstance(a, dict) and a.get("name") == "version.json"), None)
        if not asset or not isinstance(asset.get("browser_download_url"), str):
            raise ValueError("The latest release has no downloadable version.json asset.")
        source = asset["browser_download_url"]
        candidate_url = str(release.get("html_url", ""))
        if candidate_url.startswith("https://github.com/"):
            release_url = candidate_url
    manifest = read_json(source)
    latest = manifest.get("version")
    if not isinstance(latest, str):
        raise ValueError("version.json must include a version string.")
    try:
        newer = Version(latest) > Version(__version__)
    except InvalidVersion as exc:
        raise ValueError("version.json contains an invalid version.") from exc
    return UpdateResult(latest, newer, release_url, source)
