"""sizy — интерактивный обзор размеров файлов и папок в терминале."""

from __future__ import annotations

import argparse
import os
import sys


def _configure_stdio() -> None:
    """Force UTF-8 on stdout/stderr.

    On Windows, redirected output (pipes, files, CI) defaults to the ANSI
    code page, which cannot encode Russian text in ``--help``. Reconfiguring
    to UTF-8 makes console and redirected output behave the same.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def main() -> None:
    _configure_stdio()
    parser = argparse.ArgumentParser(
        prog="sizy",
        description="Интерактивный обзор размеров файлов и папок в терминале.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="директория для сканирования (по умолчанию текущая)",
    )
    args = parser.parse_args()

    path = os.path.abspath(os.path.expanduser(args.path))
    if not os.path.isdir(path):
        parser.error(f"не найдена директория: {path}")

    from sizy.app import SizyApp

    SizyApp(path).run()
