"""sizy — интерактивный обзор размеров файлов и папок в терминале."""

from __future__ import annotations

import argparse
import os


def main() -> None:
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
