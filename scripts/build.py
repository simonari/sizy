#!/usr/bin/env python3
"""Build a standalone sizy binary for the current OS with PyInstaller.

PyInstaller cannot cross-compile: run this script on macOS, Linux and Windows
to get a binary for each platform. The CI workflow does exactly that.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"

OS_NAMES = {
    "darwin": "macos",
    "linux": "linux",
    "win32": "windows",
}
MACHINE_NAMES = {
    "AMD64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def main() -> None:
    if sys.platform not in OS_NAMES:
        raise SystemExit(f"unsupported platform: {sys.platform}")

    os_name = OS_NAMES[sys.platform]
    arch = MACHINE_NAMES.get(platform.machine(), platform.machine().lower())

    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(ROOT / "scripts" / "entrypoint.py"),
            "--name",
            "sizy",
            "--onefile",
            "--clean",
            "--noconfirm",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD),
            "--specpath",
            str(BUILD),
            "--paths",
            str(ROOT / "src"),
            # Textual loads widgets and styles dynamically, so collect the
            # whole package (including its data files) instead of relying on
            # static import analysis.
            "--collect-all",
            "textual",
            "--copy-metadata",
            "textual",
            "--copy-metadata",
            "rich",
        ],
        check=True,
        cwd=ROOT,
    )

    binary = DIST / ("sizy.exe" if os.name == "nt" else "sizy")
    if not binary.is_file():
        raise SystemExit(f"expected binary was not produced: {binary}")

    target = DIST / f"sizy-{os_name}-{arch}{binary.suffix}"
    shutil.copy2(binary, target)

    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"\nBuilt {target} ({size_mb:.1f} MiB)")


if __name__ == "__main__":
    main()
