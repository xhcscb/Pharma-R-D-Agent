"""检查项目 Markdown 本地链接和研究模块基本状态。"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "data",
    "htmlcov",
    "node_modules",
}
REQUIRED_NAVIGATION = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/README.md",
    "docs/data_layer/README.md",
    "research/README.md",
)
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)\n]+)\)")


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in REPO_ROOT.rglob("*.md")
        if not any(part in IGNORED_DIRS for part in path.relative_to(REPO_ROOT).parts)
    )


def normalize_local_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    elif " " in target:
        target = target.split(" ", 1)[0]

    lowered = target.lower()
    if not target or target.startswith("#"):
        return None
    if lowered.startswith(("http://", "https://", "mailto:", "data:", "javascript:")):
        return None

    target = unquote(target).split("#", 1)[0].split("?", 1)[0]
    return target or None


def check_links() -> list[str]:
    errors: list[str] = []
    for source in markdown_files():
        text = source.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(text):
            target = normalize_local_target(raw_target)
            if target is None:
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.exists():
                relative_source = source.relative_to(REPO_ROOT)
                errors.append(f"{relative_source}: 本地链接不存在 -> {target}")
    return errors


def count_csv_rows(relative_path: str) -> int:
    with (REPO_ROOT / relative_path).open(encoding="utf-8-sig", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def main() -> int:
    errors: list[str] = []
    for relative_path in REQUIRED_NAVIGATION:
        if not (REPO_ROOT / relative_path).is_file():
            errors.append(f"缺少文档入口：{relative_path}")

    errors.extend(check_links())

    print("文档检查摘要")
    print(f"  Markdown 文件：{len(markdown_files())}")
    print(f"  错误：{len(errors)}")
    print("研究模块当前记录数（仅报告，不代表验收通过）")
    for path in (
        "research/search/seed_set.csv",
        "research/search/search_log.csv",
        "research/screening/screening_decisions.csv",
        "research/screening/quality_appraisal.csv",
        "research/evidence/literature_matrix.csv",
    ):
        print(f"  {path}: {count_csv_rows(path)}")

    for error in errors:
        print(f"错误：{error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
