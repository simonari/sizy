"""Textual user interface for sizy."""

from __future__ import annotations

import os
import threading

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, ProgressBar, Static

from .scanner import Entry, ScanResult, Scanner

HOME = os.path.expanduser("~")
NAME_COLUMN_WIDTH = 48


def human_size(size: int) -> str:
    """Format a byte count compactly, e.g. ``1.2 GiB``."""
    if size < 1024:
        return f"{size} B"
    value = float(size)
    unit = "B"
    for unit in ("KiB", "MiB", "GiB", "TiB", "PiB"):
        value /= 1024
        if value < 1024:
            break
    return f"{value:.1f} {unit}"


def count_text(number: int) -> str:
    """Thousands separated with spaces: ``1 234 567``."""
    return f"{number:,}".replace(",", " ")


def compact_path(path: str) -> str:
    """Abbreviate the home directory to ``~``."""
    if path == HOME:
        return "~"
    if path.startswith(HOME + os.sep):
        return "~" + path[len(HOME) :]
    return path


def share_bar(fraction: float, width: int = 16) -> Text:
    """A unicode progress bar plus a percentage, e.g. ``████░…… 42.0%``."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    bar = Text()
    bar.append("█" * filled, style="cyan")
    bar.append("░" * (width - filled), style="bright_black")
    bar.append(f" {fraction:5.1%}")
    return bar


class SizyApp(App[None]):
    """Interactive disk usage explorer."""

    TITLE = "sizy"
    SUB_TITLE = "размеры файлов и папок"

    CSS = """
    Screen { layout: vertical; }
    #crumb {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text;
        text-style: bold;
    }
    #summary { height: 1; padding: 0 1; color: $text-muted; }
    #table { height: 1fr; }
    #progress { height: 1; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    """

    BINDINGS = [
        Binding("q", "quit", "Выход"),
        Binding("enter", "open", "Открыть", priority=True),
        Binding("backspace", "up", "Наверх"),
        Binding("s", "cycle_sort", "Сортировка"),
        Binding("r", "rescan", "Скан заново"),
    ]

    def __init__(self, path: str) -> None:
        super().__init__()
        self._start_path = os.path.abspath(path)
        self._root: Entry | None = None
        self._current: Entry | None = None
        self._parents: list[Entry] = []
        self._rows: list[Entry] = []
        self._sort_mode = "size"
        self._cancel = threading.Event()
        self._scanning = False

    def compose(self) -> ComposeResult:
        yield Static(Text(compact_path(self._start_path)), id="crumb")
        yield Static("", id="summary")
        yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield ProgressBar(id="progress", total=None)
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Имя", key="name", width=NAME_COLUMN_WIDTH)
        table.add_column("Размер", key="size", width=10)
        table.add_column("Доля", key="share", width=23)
        table.add_column("Объектов", key="items", width=11)
        self.query_one(ProgressBar).display = False
        self._start_scan()

    def on_unmount(self) -> None:
        self._cancel.set()

    # -- scanning ----------------------------------------------------------

    def _start_scan(self) -> None:
        self._cancel.set()
        cancel = threading.Event()
        self._cancel = cancel
        self._scanning = True
        self._root = None
        self._current = None
        self._parents.clear()
        self._rows = []

        self.query_one(DataTable).clear(columns=False)
        self.query_one("#crumb", Static).update(Text(compact_path(self._start_path)))
        self.query_one("#summary", Static).update("")
        self.query_one("#status", Static).update(
            Text("Сканирование…", style="italic")
        )
        self.query_one(ProgressBar).display = True
        self._scan_worker(self._start_path, cancel)

    @work(thread=True, exclusive=True)
    def _scan_worker(self, path: str, cancel: threading.Event) -> None:
        def progress(scanned: int, current: str) -> None:
            self._call_soon(self._show_scan_progress, cancel, scanned, current)

        scanner = Scanner(path, progress=progress, cancel=cancel)
        try:
            result = scanner.scan()
        except Exception as error:  # noqa: BLE001 - surfaced in the status line
            self._call_soon(self._scan_failed, cancel, str(error))
            return
        self._call_soon(self._scan_finished, cancel, result)

    def _call_soon(self, callback, *args) -> None:
        try:
            self.call_from_thread(callback, *args)
        except RuntimeError:
            pass  # the app is shutting down

    def _show_scan_progress(
        self, cancel: threading.Event, scanned: int, path: str
    ) -> None:
        if cancel is not self._cancel or not self._scanning:
            return
        self.query_one("#status", Static).update(
            Text(
                f"Сканирование… {count_text(scanned)} объектов"
                f" · {compact_path(path)}",
                style="italic",
            )
        )

    def _scan_finished(self, cancel: threading.Event, result: ScanResult) -> None:
        if cancel is not self._cancel or result.cancelled:
            return
        self._scanning = False
        self._root = result.root
        self._current = result.root
        self._parents.clear()
        self.query_one(ProgressBar).display = False

        status = Text(
            f"Готово за {result.elapsed:.1f} с"
            f" · осмотрено {count_text(result.scanned)} объектов"
        )
        if result.errors:
            status.append(
                f" · ошибок доступа: {count_text(result.errors)}", style="yellow"
            )
        self.query_one("#status", Static).update(status)
        self._render()

    def _scan_failed(self, cancel: threading.Event, message: str) -> None:
        if cancel is not self._cancel:
            return
        self._scanning = False
        self.query_one(ProgressBar).display = False
        self.query_one("#status", Static).update(
            Text(f"Ошибка сканирования: {message}", style="bold red")
        )

    # -- rendering ---------------------------------------------------------

    def _set_crumb(self, path: str) -> None:
        self.query_one("#crumb", Static).update(Text(compact_path(path)))

    def _render(self) -> None:
        entry = self._current
        if entry is None:
            return

        self._set_crumb(entry.path)
        summary = Text(
            f"Итого: {human_size(entry.size)} · объектов: {count_text(entry.items)}"
        )
        if entry.errors:
            summary.append(
                f" · ошибок доступа: {count_text(entry.errors)}", style="yellow"
            )
        self.query_one("#summary", Static).update(summary)

        children = list(entry.children)
        if self._sort_mode == "name":
            children.sort(key=lambda item: (not item.is_dir, item.name.casefold()))
        else:
            children.sort(key=lambda item: (-item.size, item.name.casefold()))
        self._rows = children

        rows: list[tuple[Text, str, Text, str]] = []
        total = entry.size
        for child in children:
            fraction = child.size / total if total else 0.0

            name = Text()
            if child.is_dir:
                name.append(child.name + "/", style="bold cyan")
            else:
                name.append(child.name)
                if child.symlink:
                    name.append("@", style="magenta")
            if child.errors:
                name.append(f" !{count_text(child.errors)}", style="red")

            rows.append(
                (
                    name,
                    human_size(child.size).rjust(10),
                    share_bar(fraction),
                    (count_text(child.items) if child.is_dir else "").rjust(11),
                )
            )

        table = self.query_one(DataTable)
        table.clear(columns=False)
        if rows:
            table.add_rows(rows)
            table.move_cursor(row=0)

    # -- actions -----------------------------------------------------------

    def action_open(self) -> None:
        table = self.query_one(DataTable)
        if not self._rows:
            return
        row = table.cursor_row
        if not 0 <= row < len(self._rows):
            return
        target = self._rows[row]
        if target.is_dir:
            assert self._current is not None
            self._parents.append(self._current)
            self._current = target
            self._render()

    def action_up(self) -> None:
        if self._current is None or not self._parents:
            return
        self._current = self._parents.pop()
        self._render()

    def action_cycle_sort(self) -> None:
        self._sort_mode = "name" if self._sort_mode == "size" else "size"
        self._render()
        label = "по имени" if self._sort_mode == "name" else "по размеру"
        self.notify(f"Сортировка: {label}", timeout=1.5)

    def action_rescan(self) -> None:
        self._start_scan()
