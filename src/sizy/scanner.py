"""Filesystem scanning and size aggregation for sizy."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Callable

ProgressCallback = Callable[[int, str], None]


@dataclass(slots=True)
class Entry:
    """A single file or directory in the scanned tree."""

    name: str
    path: str
    is_dir: bool
    symlink: bool = False
    size: int = 0
    disk: int = 0
    items: int = 0
    errors: int = 0
    children: list[Entry] = field(default_factory=list)


@dataclass(slots=True)
class ScanResult:
    root: Entry
    elapsed: float
    scanned: int
    errors: int
    cancelled: bool


class Scanner:
    """Walk a directory tree and aggregate file sizes bottom-up.

    - symlinks are not followed (the link itself is counted);
    - hard links are counted once per (device, inode);
    - mount points are skipped when *one_filesystem* is true;
    - unreadable files and directories are skipped and counted as errors.
    """

    def __init__(
        self,
        root: str,
        *,
        one_filesystem: bool = True,
        progress: ProgressCallback | None = None,
        cancel: threading.Event | None = None,
        progress_interval: float = 0.1,
    ) -> None:
        self.root = os.path.abspath(root)
        self.one_filesystem = one_filesystem
        self.progress = progress
        self.cancel = cancel if cancel is not None else threading.Event()
        self.progress_interval = progress_interval

        self._root_device: int | None = None
        self._seen_links: set[tuple[int, int]] = set()
        self._scanned = 0
        self._last_progress = 0.0
        self._cancelled = False

    def scan(self) -> ScanResult:
        started = time.monotonic()
        name = os.path.basename(self.root.rstrip(os.sep)) or self.root
        root = Entry(name=name, path=self.root, is_dir=True)
        try:
            self._root_device = os.stat(self.root).st_dev
        except OSError:
            self._root_device = None

        self._walk(root)
        self._emit_progress(self.root, force=True)

        return ScanResult(
            root=root,
            elapsed=time.monotonic() - started,
            scanned=self._scanned,
            errors=root.errors,
            cancelled=self._cancelled,
        )

    # -- traversal ---------------------------------------------------------

    def _walk(self, root: Entry) -> None:
        root_iterator = self._open_dir(root.path)
        if root_iterator is None:
            root.errors += 1
            return

        # Iterative post-order traversal: a directory's totals are added to
        # its parent when its iterator is exhausted.
        stack: list[tuple[Entry, Iterator[os.DirEntry[str]] | None]] = [
            (root, root_iterator)
        ]
        while stack:
            if self.cancel.is_set():
                self._cancelled = True
                break

            entry, iterator = stack[-1]
            if iterator is None:
                stack.pop()
                if stack:
                    self._absorb(stack[-1][0], entry)
                continue

            try:
                dirent = next(iterator)
            except StopIteration:
                iterator.close()
                stack[-1] = (entry, None)
                continue
            except OSError:
                iterator.close()
                stack[-1] = (entry, None)
                entry.errors += 1
                continue

            self._scanned += 1
            child = self._handle_dirent(entry, dirent)
            if child is not None:
                child_iterator = self._open_dir(child.path)
                if child_iterator is None:
                    child.errors += 1
                    self._absorb(entry, child)
                else:
                    stack.append((child, child_iterator))
            self._emit_progress(entry.path)

        for _, iterator in stack:
            if iterator is not None:
                iterator.close()

    def _handle_dirent(self, parent: Entry, dirent: os.DirEntry[str]) -> Entry | None:
        """Account for one directory entry.

        Returns the entry when it is a directory that should be descended into.
        """
        try:
            stat = dirent.stat(follow_symlinks=False)
            is_symlink = dirent.is_symlink()
            is_dir = dirent.is_dir(follow_symlinks=False) and not is_symlink
        except OSError:
            parent.errors += 1
            return None

        if is_dir and self.one_filesystem and self._root_device is not None:
            if stat.st_dev != self._root_device:
                return None

        child = Entry(
            name=dirent.name,
            path=dirent.path,
            is_dir=is_dir,
            symlink=is_symlink,
        )
        parent.children.append(child)
        parent.items += 1

        if is_dir:
            return child

        size = stat.st_size
        disk = _allocated_size(stat)
        if not is_symlink and stat.st_nlink > 1:
            key = (stat.st_dev, stat.st_ino)
            if key in self._seen_links:
                # Same inode counted already: it takes no extra space.
                size = 0
                disk = 0
            else:
                self._seen_links.add(key)

        child.size = size
        child.disk = disk
        parent.size += size
        parent.disk += disk
        return None

    @staticmethod
    def _absorb(parent: Entry, child: Entry) -> None:
        parent.size += child.size
        parent.disk += child.disk
        parent.items += child.items
        parent.errors += child.errors

    @staticmethod
    def _open_dir(path: str) -> Iterator[os.DirEntry[str]] | None:
        try:
            return os.scandir(path)
        except OSError:
            return None

    def _emit_progress(self, path: str, *, force: bool = False) -> None:
        if self.progress is None:
            return
        now = time.monotonic()
        if not force and now - self._last_progress < self.progress_interval:
            return
        self._last_progress = now
        self.progress(self._scanned, path)


def _allocated_size(stat: os.stat_result) -> int:
    """Bytes actually allocated on disk, when the platform reports it."""
    blocks = getattr(stat, "st_blocks", None)
    if blocks is None:
        return stat.st_size
    return blocks * 512
