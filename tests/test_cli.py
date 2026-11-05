"""Tests for the command-line entry points."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sizy", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_help() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    assert "usage: sizy" in result.stdout
    assert "директория для сканирования" in result.stdout


def test_missing_directory_is_rejected(tmp_path: Path) -> None:
    result = run_cli(str(tmp_path / "missing"))

    assert result.returncode == 2
    assert "не найдена директория" in result.stderr
