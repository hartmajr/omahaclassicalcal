"""Scan the working tree for credentials before making a repo public.

GitHub Actions keeps `secrets.*` out of your files by design. The realistic
way a key leaks from THIS project is human: pasting it into a file to test
something locally, or committing a .env. Run this before you flip the repo
to public, and after any local debugging session.

    python scripts/check_secrets.py

Exits nonzero if anything looks like a credential.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Patterns worth stopping on. Kept deliberately narrow: a scanner that cries
# wolf is one people learn to ignore.
PATTERNS = [
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Generic assigned secret",
     re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[=:]\s*"
                r"['\"][A-Za-z0-9_\-]{16,}['\"]")),
]

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}
SKIP_FILES = {"check_secrets.py"}          # this file contains the patterns
TEXT_SUFFIXES = {".py", ".yml", ".yaml", ".json", ".md", ".txt", ".ics",
                 ".html", ".cfg", ".ini", ".toml", ".env", ""}


def scan() -> list[tuple[Path, int, str]]:
    hits = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    hits.append((path.relative_to(ROOT), lineno, label))
    return hits


def main() -> int:
    # A committed .env is the single most common way this goes wrong.
    env_file = ROOT / ".env"
    hits = scan()
    if env_file.exists():
        print("WARNING: a .env file exists. It is gitignored, but make sure "
              "it was never committed:  git log --all -- .env")
    if hits:
        print("\nPossible credentials found:")
        for path, lineno, label in hits:
            print(f"  {path}:{lineno}  [{label}]")
        print("\nRemove them before making this repository public. If any was "
              "already committed, rotate the key -- deleting the line does "
              "NOT remove it from git history.")
        return 1
    print("No credentials found in the working tree.")
    print("Reminder: git history is separate. Before going public, check\n"
          "  git log -p | grep -i 'sk-ant'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
