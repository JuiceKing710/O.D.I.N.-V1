#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.backend.core.memory_manager import MemoryManager


def init_db(db_path: Path) -> None:
    MemoryManager(db_path)
    print(f"Initialized database at {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis management utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Initialize the SQLite database")
    init_parser.add_argument("--db", default="data/jarvis.db", type=Path)

    args = parser.parse_args()
    if args.command == "init-db":
        init_db(args.db)


if __name__ == "__main__":
    main()
