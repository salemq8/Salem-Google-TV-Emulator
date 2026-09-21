"""Package catalog parsing, retained for diagnostics and compatibility tests."""
import re
from dataclasses import dataclass

SYSTEM_IMAGE_PATTERN = re.compile(r"system-images;android-(?P<api>\d+);(?P<tag>[^;\s|]+);(?P<abi>[^;\s|]+)")
ABI_TIE_BREAKER = {"x86_64": 40, "x86": 30, "arm64-v8a": 20, "aarch64": 20}

class SetupError(ValueError):
    pass


@dataclass(frozen=True)
class SystemImagePackage:
    package: str
    api_level: int
    tag: str
    abi: str
    tv_type: str | None
    description: str = ""

    @property
    def tv_label(self) -> str:
        if self.tv_type == "google_tv":
            return "Google TV"
        return "System Image"

    def detail(self) -> str:
        description = f" | {self.description}" if self.description else ""
        return f"{self.tv_label}: API {self.api_level}, {self.tag}, {self.abi} -> {self.package}{description}"


def _parse_system_images(output: str) -> list[SystemImagePackage]:
    images: dict[str, SystemImagePackage] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        description = _description_from_sdkmanager_line(line)
        for match in SYSTEM_IMAGE_PATTERN.finditer(line):
            package = match.group(0).rstrip(".,;")
            api_level = int(match.group("api"))
            tag = match.group("tag").strip()
            abi = match.group("abi").strip().rstrip(".,;")
            images[package] = SystemImagePackage(
                package=package,
                api_level=api_level,
                tag=tag,
                abi=abi,
                tv_type=_classify_system_image(tag, description),
                description=description,
            )
    return sorted(images.values(), key=lambda image: (image.package, image.description))


def _description_from_sdkmanager_line(line: str) -> str:
    if "|" not in line:
        return ""
    parts = [part.strip() for part in line.split("|")]
    if len(parts) >= 3:
        return parts[-1]
    return ""


def _classify_system_image(tag: str, description: str) -> str | None:
    normalized_tag = _normalize_token(tag)
    normalized_description = _normalize_token(description)
    haystack = f"{normalized_tag} {normalized_description}"
    if "google" in haystack and "tv" in haystack:
        return "google_tv"
    return None


def _select_system_image(images: list[SystemImagePackage], tv_type: str) -> SystemImagePackage | None:
    candidates = [image for image in images if image.tv_type == tv_type]
    if not candidates:
        return None
    return sorted(candidates, key=lambda image: (image.api_level, _abi_score(image.abi), image.package), reverse=True)[0]


def _manual_system_image(package_text: str | None, tv_type: str) -> SystemImagePackage | None:
    package = (package_text or "").strip().strip('"').strip("'")
    if not package:
        return None
    match = SYSTEM_IMAGE_PATTERN.fullmatch(package)
    if not match:
        raise SetupError(f"Manual package is not a full system-image path: {package}")
    return SystemImagePackage(
        package=package,
        api_level=int(match.group("api")),
        tag=match.group("tag").strip(),
        abi=match.group("abi").strip(),
        tv_type=tv_type,
        description="Manual selection",
    )


def _abi_score(abi: str) -> int:
    return ABI_TIE_BREAKER.get(abi.lower(), 0)


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())
