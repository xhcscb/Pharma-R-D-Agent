"""Validate that every CSV row has the same width as its header."""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    problems: list[str] = []

    for path in sorted(repo_root.rglob("*.csv")):
        if path.name.endswith(".corrected.csv"):
            continue
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))

        relative_path = path.relative_to(repo_root)
        if not rows:
            problems.append(f"{relative_path}: file is empty")
            continue

        expected_width = len(rows[0])
        bad_rows = [index for index, row in enumerate(rows[1:], start=2) if len(row) != expected_width]
        if bad_rows:
            problems.append(
                f"{relative_path}: expected {expected_width} columns; malformed rows {bad_rows}"
            )

    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1

    print("CSV shape validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
