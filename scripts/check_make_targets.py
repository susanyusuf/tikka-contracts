#!/usr/bin/env python3
"""Fail when a ``.PHONY`` target in the Makefile has no rule (issue #1173).

A ``.PHONY`` name without a recipe is a silent no-op in ``make``: it always
"succeeds" without running anything, so a typo'd or deleted target can slip
through CI.  This checker parses the ``.PHONY:`` declaration and verifies that
every listed name also has a ``name:`` rule elsewhere in the file.

Usage:
    python scripts/check_make_targets.py

Exits non-zero when a phony target is missing a rule.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MAKEFILE = Path(__file__).resolve().parent.parent / "Makefile"


def parse_phony(text: str) -> list[str]:
    """Return the target names listed in the ``.PHONY:`` declaration."""
    match = re.search(
        r"^\.PHONY:(.*?)(?=^\S|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return []
    return [token for token in match.group(1).replace("\\", " ").split() if token]


def defined_targets(text: str) -> set[str]:
    """Return every target name that starts a rule (``name:`` at column 0)."""
    return set(re.findall(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", text, re.MULTILINE))


def main() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    phony = parse_phony(text)
    if not phony:
        print("ERROR: no .PHONY targets found in Makefile", file=sys.stderr)
        sys.exit(1)

    defined = defined_targets(text)
    missing = [target for target in phony if target not in defined]
    if missing:
        print(
            "ERROR: .PHONY targets without recipes: " + " ".join(missing),
            file=sys.stderr,
        )
        print(
            "Add a recipe or remove the name from .PHONY.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"OK: all {len(phony)} .PHONY targets have recipes.")
    sys.exit(0)


if __name__ == "__main__":
    main()
