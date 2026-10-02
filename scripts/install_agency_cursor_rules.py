"""Convert agency-agents .md files to Cursor .mdc rules (Windows-friendly)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

AGENT_DIRS = [
    "academic",
    "design",
    "engineering",
    "finance",
    "game-development",
    "marketing",
    "paid-media",
    "product",
    "project-management",
    "sales",
    "spatial-computing",
    "specialized",
    "strategy",
    "support",
    "testing",
]


def get_field(field: str, text: str) -> str:
    in_fm = False
    for line in text.splitlines():
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            break
        if in_fm and line.startswith(f"{field}: "):
            return line[len(field) + 2 :]
    return ""


def get_body(text: str) -> str:
    parts = text.split("---")
    if len(parts) >= 3:
        return "---".join(parts[2:]).lstrip("\n")
    return text


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def convert(repo: Path, dest: Path) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for dirname in AGENT_DIRS:
        folder = repo / dirname
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            name = get_field("name", text) or path.stem
            desc = get_field("description", text) or name
            slug = slugify(name)
            body = get_body(text)
            front = (
                "---\n"
                f"description: {desc}\n"
                'globs: ""\n'
                "alwaysApply: false\n"
                "---\n"
            )
            (dest / f"{slug}.mdc").write_text(front + body, encoding="utf-8")
            count += 1
    return count


def main() -> int:
    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else repo / ".cursor" / "rules"
    n = convert(repo, dest)
    print(f"Installed {n} rules to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
