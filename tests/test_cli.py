"""Tests for the command-line entry points."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def run_cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    # Keep the output as bytes: the CLI writes UTF-8, while the Windows
    # locale (cp1252) would fail to decode Russian text in text mode.
    return subprocess.run(
        [sys.executable, "-m", "sizy", *args],
        capture_output=True,
        timeout=30,
    )


def test_help() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    stdout = result.stdout.decode("utf-8")
    assert "usage: sizy" in stdout
    assert "директория для сканирования" in stdout


def test_help_with_non_utf8_stdio() -> None:
    """Reproduce Windows CI: redirected output defaults to cp1252."""
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [sys.executable, "-m", "sizy", "--help"],
        capture_output=True,
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    decoded = result.stdout.decode("utf-8")
    assert "usage: sizy" in decoded
    assert "директория для сканирования" in decoded


@pytest.mark.skipif(os.name != "nt", reason="Windows drive semantics")
def test_bare_drive_is_expanded_to_root() -> None:
    from sizy import _normalize_path

    assert _normalize_path("C:") == os.path.abspath("C:" + os.sep)


def test_missing_directory_is_rejected(tmp_path: Path) -> None:
    result = run_cli(str(tmp_path / "missing"))

    assert result.returncode == 2
    assert "не найдена директория" in result.stderr.decode("utf-8", "replace")
