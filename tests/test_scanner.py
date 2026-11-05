"""Tests for the filesystem scanner."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from sizy.scanner import Scanner


def make_file(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_scan_aggregates_sizes_and_items(tmp_path: Path) -> None:
    make_file(tmp_path / "big.bin", 10_000)
    make_file(tmp_path / "sub" / "small.bin", 1_500)
    make_file(tmp_path / "sub" / "deep" / "tiny.bin", 500)
    (tmp_path / "empty").mkdir()

    result = Scanner(str(tmp_path)).scan()

    assert result.cancelled is False
    assert result.errors == 0
    assert result.root.path == str(tmp_path)
    assert result.root.size == 12_000
    assert result.root.items == 6  # all files and dirs below the root
    assert result.scanned == 6
    assert result.elapsed >= 0

    by_name = {child.name: child for child in result.root.children}
    assert set(by_name) == {"big.bin", "sub", "empty"}

    assert by_name["big.bin"].is_dir is False
    assert by_name["big.bin"].size == 10_000
    assert by_name["sub"].is_dir is True
    assert by_name["sub"].size == 2_000
    assert by_name["sub"].items == 3  # small.bin, deep, tiny.bin
    assert by_name["empty"].size == 0
    assert by_name["empty"].children == []


def test_empty_directory(tmp_path: Path) -> None:
    result = Scanner(str(tmp_path)).scan()

    assert result.root.size == 0
    assert result.root.items == 0
    assert result.root.children == []
    assert result.errors == 0


def test_missing_root_is_an_error(tmp_path: Path) -> None:
    result = Scanner(str(tmp_path / "missing")).scan()

    assert result.errors == 1
    assert result.root.size == 0
    assert result.root.items == 0
    assert result.cancelled is False


def test_hardlinks_are_counted_once(tmp_path: Path) -> None:
    original = make_file(tmp_path / "original.bin", 4_096)
    try:
        os.link(original, tmp_path / "second-link.bin")
    except OSError as error:  # pragma: no cover - filesystem limitation
        pytest.skip(f"hard links are not supported here: {error}")
    make_file(tmp_path / "other.bin", 1_000)

    result = Scanner(str(tmp_path)).scan()

    assert result.root.size == 5_096
    linked = [child for child in result.root.children if child.name != "other.bin"]
    assert sorted(child.size for child in linked) == [0, 4_096]


def test_symlinks_are_not_followed(tmp_path: Path) -> None:
    target = make_file(tmp_path / "target.bin", 100_000)
    real_dir = tmp_path / "real-dir"
    make_file(real_dir / "inner.bin", 50)

    link = tmp_path / "link.bin"
    dir_link = tmp_path / "dir-link"
    try:
        link.symlink_to(target)
        dir_link.symlink_to(real_dir, target_is_directory=True)
    except OSError as error:  # pragma: no cover - Windows without privileges
        pytest.skip(f"symlinks are not supported here: {error}")

    result = Scanner(str(tmp_path)).scan()

    link_stat = os.lstat(link)
    dir_link_stat = os.lstat(dir_link)
    assert result.root.size == 100_000 + 50 + link_stat.st_size + dir_link_stat.st_size

    by_name = {child.name: child for child in result.root.children}
    assert by_name["link.bin"].symlink is True
    assert by_name["link.bin"].is_dir is False
    assert by_name["link.bin"].size == link_stat.st_size
    assert by_name["dir-link"].symlink is True
    assert by_name["dir-link"].is_dir is False
    assert by_name["dir-link"].children == []
    # The real directory is scanned exactly once.
    assert by_name["real-dir"].size == 50


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores directory permissions",
)
def test_unreadable_directory_is_reported(tmp_path: Path) -> None:
    make_file(tmp_path / "visible.bin", 500)
    blocked = tmp_path / "blocked"
    make_file(blocked / "secret.bin", 1_000)

    blocked.chmod(0)
    try:
        result = Scanner(str(tmp_path)).scan()
    finally:
        blocked.chmod(0o700)

    assert result.root.size == 500
    assert result.errors >= 1
    blocked_entry = next(
        child for child in result.root.children if child.name == "blocked"
    )
    assert blocked_entry.errors >= 1
    assert blocked_entry.children == []


def test_cancelled_scan_stops_immediately(tmp_path: Path) -> None:
    make_file(tmp_path / "file.bin", 10)
    cancel = threading.Event()
    cancel.set()

    result = Scanner(str(tmp_path), cancel=cancel).scan()

    assert result.cancelled is True
    assert result.scanned == 0
    assert result.root.children == []


def test_cancellation_stops_mid_scan(tmp_path: Path) -> None:
    for index in range(100):
        make_file(tmp_path / f"file-{index}.bin", 1)

    cancel = threading.Event()

    def progress(scanned: int, path: str) -> None:
        if scanned >= 2:
            cancel.set()

    result = Scanner(
        str(tmp_path),
        progress=progress,
        cancel=cancel,
        progress_interval=0,
    ).scan()

    assert result.cancelled is True
    assert 2 <= result.scanned < 100


def test_progress_callback_reports_final_state(tmp_path: Path) -> None:
    for index in range(5):
        make_file(tmp_path / f"file-{index}.bin", 10)

    calls: list[tuple[int, str]] = []
    result = Scanner(
        str(tmp_path), progress=lambda scanned, path: calls.append((scanned, path))
    ).scan()

    assert calls, "the scanner should report progress at least once"
    assert calls[-1][0] == result.scanned == 5
    assert calls[-1][1] == str(tmp_path)
