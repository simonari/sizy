"""Tests for the Textual application and formatting helpers."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import DataTable

from sizy import app as app_module
from sizy.app import SizyApp, compact_path, count_text, human_size, share_bar


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A small known tree:

    root/
    ├── a.bin        5000 B
    ├── alpha/
    │   ├── b.bin    2000 B
    │   └── nested/
    │       └── c.bin 1000 B
    └── beta/        empty
    """
    (tmp_path / "a.bin").write_bytes(b"x" * 5_000)
    alpha = tmp_path / "alpha"
    (alpha / "nested").mkdir(parents=True)
    (alpha / "b.bin").write_bytes(b"x" * 2_000)
    (alpha / "nested" / "c.bin").write_bytes(b"x" * 1_000)
    (tmp_path / "beta").mkdir()
    return tmp_path


async def wait_for_scan(
    app: SizyApp, pilot: Pilot, timeout: float = 10.0
) -> None:
    deadline = time.monotonic() + timeout
    while app._scanning or app._root is None:
        if time.monotonic() > deadline:
            raise AssertionError("scan did not finish in time")
        await pilot.pause(0.02)


# -- formatting helpers ----------------------------------------------------


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1536, "1.5 KiB"),
        (1024**2, "1.0 MiB"),
        (1024**3, "1.0 GiB"),
        (1024**4, "1.0 TiB"),
        (1024**5, "1.0 PiB"),
    ],
)
def test_human_size(size: int, expected: str) -> None:
    assert human_size(size) == expected


def test_count_text() -> None:
    assert count_text(0) == "0"
    assert count_text(1_234_567) == "1 234 567"


def test_compact_path(monkeypatch: pytest.MonkeyPatch) -> None:
    home = os.path.join(os.sep, "home", "user")
    monkeypatch.setattr(app_module, "HOME", home)

    assert compact_path(home) == "~"
    assert compact_path(os.path.join(home, "projects")) == "~" + os.sep + "projects"
    other = os.path.join(os.sep, "tmp")
    assert compact_path(other) == other


def test_share_bar() -> None:
    assert share_bar(0).plain == "░" * 16 + "  0.0%"
    assert share_bar(0.5).plain == "█" * 8 + "░" * 8 + " 50.0%"
    assert share_bar(1).plain == "█" * 16 + " 100.0%"
    # Fractions outside [0, 1] are clamped.
    assert share_bar(2).plain == share_bar(1).plain
    assert share_bar(-1).plain == share_bar(0).plain


# -- app behaviour ---------------------------------------------------------


async def test_app_scans_and_lists_entries(tree: Path) -> None:
    app = SizyApp(str(tree))
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for_scan(app, pilot)

        table = app.query_one(DataTable)
        assert app._root is not None
        assert app._root.size == 8_000
        assert table.row_count == 3
        assert [entry.name for entry in app._rows] == ["a.bin", "alpha", "beta"]
        assert [entry.size for entry in app._rows] == [5_000, 3_000, 0]


async def test_app_navigates_into_directories(tree: Path) -> None:
    app = SizyApp(str(tree))
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for_scan(app, pilot)
        table = app.query_one(DataTable)
        table.focus()
        await pilot.pause()

        # First row is a file: Enter must not navigate.
        await pilot.press("enter")
        await pilot.pause()
        assert app._current is app._root

        # Move to "alpha" and open it.
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert app._current is not None
        assert app._current.name == "alpha"
        assert [entry.name for entry in app._rows] == ["b.bin", "nested"]
        assert table.row_count == 2

        # Backspace returns to the parent directory.
        await pilot.press("backspace")
        await pilot.pause()
        assert app._current is app._root
        assert table.row_count == 3
        assert [entry.name for entry in app._rows] == ["a.bin", "alpha", "beta"]


async def test_app_sort_toggle(tree: Path) -> None:
    app = SizyApp(str(tree))
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for_scan(app, pilot)
        table = app.query_one(DataTable)
        table.focus()
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        assert app._sort_mode == "name"
        # Directories first, then alphabetically.
        assert [entry.name for entry in app._rows] == ["alpha", "beta", "a.bin"]

        await pilot.press("s")
        await pilot.pause()
        assert app._sort_mode == "size"
        assert [entry.name for entry in app._rows] == ["a.bin", "alpha", "beta"]


async def test_app_rescan_picks_up_new_files(tree: Path) -> None:
    app = SizyApp(str(tree))
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for_scan(app, pilot)
        table = app.query_one(DataTable)
        assert table.row_count == 3

        (tree / "new.bin").write_bytes(b"x" * 7_000)
        await pilot.press("r")
        await wait_for_scan(app, pilot)

        assert app._root is not None
        assert app._root.size == 15_000
        assert table.row_count == 4
        assert [entry.name for entry in app._rows][0] == "new.bin"


async def test_app_works_in_small_terminal(tree: Path) -> None:
    app = SizyApp(str(tree))
    async with app.run_test(size=(80, 24)) as pilot:
        await wait_for_scan(app, pilot)
        assert app.query_one(DataTable).row_count == 3
