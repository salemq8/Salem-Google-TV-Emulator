"""Validate the reviewed Microsoft JDK's release metadata and stable Java versions."""
from __future__ import annotations

import configparser
import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class JavaVersion:
    number: tuple[int, ...]
    build: int | None = None
    optional: str | None = None

    @classmethod
    def parse(cls, value: str) -> JavaVersion:
        # Java's fourth (and later) version elements are significant, not ZIP revisions.
        # This production toolchain accepts stable versions only, not -ea/-internal builds.
        match = re.fullmatch(
            r"([1-9][0-9]*(?:\.(?:0|[1-9][0-9]*))*)(?:\+(0|[1-9][0-9]*)(?:-([-a-zA-Z0-9.]+))?)?",
            value,
        )
        if not match:
            raise ValueError(f"Invalid stable Java version: {value!r}")
        number = tuple(int(part) for part in match[1].split("."))
        if number[-1] == 0:
            raise ValueError(f"Java version has a trailing zero element: {value!r}")
        return cls(number, int(match[2]) if match[2] is not None else None, match[3])


@dataclass(frozen=True)
class MicrosoftJdkRelease:
    version: JavaVersion
    runtime: JavaVersion
    distribution: str

    @classmethod
    def parse(cls, text: str, pinned_version: str) -> MicrosoftJdkRelease:
        parser = configparser.ConfigParser(interpolation=None, delimiters=("=",), empty_lines_in_values=False)
        parser.optionxform = str
        try:
            parser.read_string("[release]\n" + text)
            if parser.sections() != ["release"] or parser.defaults():
                raise ValueError("Unexpected JDK release metadata section")
            metadata = {key: json.loads(value) for key, value in parser["release"].items()}
        except (configparser.Error, json.JSONDecodeError) as exc:
            raise ValueError(f"Malformed JDK release metadata: {exc}") from exc
        if not all(isinstance(value, str) for value in metadata.values()):
            raise ValueError("JDK release metadata values must be quoted strings")
        if metadata.get("IMPLEMENTOR") != "Microsoft":
            raise ValueError("JDK IMPLEMENTOR must be Microsoft")
        distribution = metadata.get("IMPLEMENTOR_VERSION", "")
        if not re.fullmatch(r"Microsoft-[0-9]+", distribution):
            raise ValueError("Missing or invalid Microsoft distribution identifier")
        if metadata.get("OS_ARCH") != "x86_64" or metadata.get("OS_NAME") != "Windows":
            raise ValueError("JDK release metadata must identify Windows x86_64")
        expected = JavaVersion.parse(pinned_version)
        version = JavaVersion.parse(metadata.get("JAVA_VERSION", ""))
        runtime = JavaVersion.parse(metadata.get("JAVA_RUNTIME_VERSION", ""))
        if version.number != expected.number or runtime.number != expected.number:
            raise ValueError(f"JDK release version does not match pinned version {pinned_version}")
        if runtime.build is None or (version.build is not None and version != runtime):
            raise ValueError("Inconsistent JDK release/runtime build metadata")
        if expected.build is not None and runtime != expected:
            raise ValueError("JDK runtime build does not match the pinned build")
        return cls(version, runtime, distribution)

    def verify_output(self, output: str) -> None:
        lines = [line.strip() for line in output.splitlines()]
        versions = [match[1] for line in lines
                    if (match := re.fullmatch(r'openjdk version "([^"\r\n]+)"(?:[ \t]+.*)?', line))]
        runtimes = [match for line in lines
                    if (match := re.fullmatch(r"OpenJDK Runtime Environment ([^()]+) \(build ([^()]+)\)", line))]
        if len(versions) != 1 or len(runtimes) != 1:
            raise ValueError("Expected one OpenJDK version and runtime banner from java -version")
        actual = JavaVersion.parse(versions[0])
        if actual.number != self.version.number or (actual.build is not None and actual != self.runtime):
            raise ValueError("java -version disagrees with the pinned release version")
        if runtimes[0][1] != self.distribution:
            raise ValueError("java -version disagrees with the Microsoft distribution metadata")
        if JavaVersion.parse(runtimes[0][2]) != self.runtime:
            raise ValueError("java -version disagrees with JAVA_RUNTIME_VERSION")
