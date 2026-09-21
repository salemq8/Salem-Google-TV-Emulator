"""Run before PyInstaller's Qt hook so missing binaries get a native error report."""
import sys
from pathlib import Path

from salem_tv_box_emulator.startup import failure, preflight

try:
    preflight()
except Exception as exc:
    report = None
    if "--self-test" in sys.argv:
        index = sys.argv.index("--self-test")
        if index + 1 < len(sys.argv):
            report = Path(sys.argv[index + 1])
    raise SystemExit(failure(exc, report=report, show_dialog=report is None))
