#!/usr/bin/env python3
"""CI check: error enums stay duplicate-free and in sync with ProtocolError.

Checks performed:

1. No duplicate discriminants (or variant names) inside any single enum:
   ``raffle-instance::Error``, ``raffle-factory::ContractError``, or the
   canonical ``raffle-shared::ProtocolError`` catalog.
2. Every live variant exists in ``ProtocolError`` with the same code.
   Instance variants compare codes directly; factory variants compare
   against the catalog's namespaced ``200-299`` entry and the factory ABI
   code recorded in its ``// factory original: N`` comment.

Usage:
    python scripts/check_error_codes.py

Exits non-zero if any check fails.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Matches `Name = 42,` plus an optional trailing `// factory original: 7`
# comment.  Doc-comment prose is never matched because variant lines must
# start with the identifier.
VARIANT_PATTERN = re.compile(
    r"^[ \t]*(\w+)[ \t]*=[ \t]*(\d+),?[ \t]*"
    r"(?://[ \t]*factory original:[ \t]*(\d+))?[ \t]*$",
    re.MULTILINE,
)


def parse_error_enum(file_path: Path, enum_name: str) -> list[tuple[int, str, int | None]]:
    """Parse ``pub enum <enum_name> { Name = code, ... }``.

    Returns ``(code, name, original_factory_code)`` triples, sorted by
    code.  The third element carries the ABI code recorded in a
    ``// factory original: N`` comment, or ``None`` when absent.  Variants
    without an explicit discriminant are skipped.

    Raises ``ValueError`` when the enum cannot be found.
    """
    content = file_path.read_text(encoding="utf-8")
    enum_match = re.search(
        r"(?:#\[contracterror\]\s*)?pub enum\s+" + re.escape(enum_name) + r"\s*\{(.*?)\}",
        content,
        re.DOTALL,
    )
    if not enum_match:
        raise ValueError(f"Could not find enum {enum_name} in {file_path}")

    errors: list[tuple[int, str, int | None]] = []
    for match in VARIANT_PATTERN.finditer(enum_match.group(1)):
        name = match.group(1)
        code = int(match.group(2))
        original_code = match.group(3)
        errors.append((code, name, int(original_code) if original_code else None))
    return errors


def check_duplicates(errors: list[tuple[int, str, int | None]], enum_name: str) -> bool:
    """Report duplicate variant names and duplicate discriminants."""
    seen_codes: dict[int, str] = {}
    seen_names: set[str] = set()
    ok = True
    for code, name, _ in errors:
        if name in seen_names:
            print(f"ERROR: Duplicate variant {name} in {enum_name}")
            ok = False
        seen_names.add(name)
        if code in seen_codes:
            print(
                f"ERROR: Duplicate discriminant {code} in {enum_name}: "
                f"{seen_codes[code]} and {name}"
            )
            ok = False
        seen_codes[code] = name
    return ok


def check_catalog(
    live_errors: list[tuple[int, str, int | None]],
    catalog_errors: list[tuple[int, str, int | None]],
    enum_name: str,
    factory: bool = False,
) -> bool:
    """Verify every live variant exists in the catalog with the same code.

    Factory ABI codes overlap instance codes, so factory variants are
    matched against the catalog's ``Factory*`` entries and their recorded
    original ABI codes while the catalog keeps them in the 200+ namespace.
    """
    catalog_by_name = {name: (code, original_code) for code, name, original_code in catalog_errors}
    ok = True
    for live_code, live_name, _ in live_errors:
        catalog_name = f"Factory{live_name}" if factory else live_name
        catalog_entry = catalog_by_name.get(catalog_name)
        if catalog_entry is None:
            print(
                f"ERROR: {enum_name}::{live_name} is missing from ProtocolError as {catalog_name}"
            )
            ok = False
            continue

        catalog_code, original_code = catalog_entry
        if factory:
            if not 200 <= catalog_code <= 299:
                print(
                    f"ERROR: ProtocolError::{catalog_name} must use a factory "
                    f"catalog code in 200-299"
                )
                ok = False
            if original_code != live_code:
                print(
                    f"ERROR: ProtocolError::{catalog_name} maps to factory ABI "
                    f"code {original_code}, but {enum_name}::{live_name} uses "
                    f"{live_code}"
                )
                ok = False
        elif catalog_code != live_code:
            print(
                f"ERROR: ProtocolError::{catalog_name} uses {catalog_code}, "
                f"but {enum_name}::{live_name} uses {live_code}"
            )
            ok = False
    return ok


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    instance_file = repo_root / "contracts" / "raffle-instance" / "src" / "lib.rs"
    factory_file = repo_root / "contracts" / "raffle-factory" / "src" / "lib.rs"
    catalog_file = repo_root / "contracts" / "raffle-shared" / "src" / "errors.rs"

    try:
        instance_errors = parse_error_enum(instance_file, "Error")
        factory_errors = parse_error_enum(factory_file, "ContractError")
        catalog_errors = parse_error_enum(catalog_file, "ProtocolError")
    except ValueError as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    ok = check_duplicates(instance_errors, "raffle-instance::Error")
    ok &= check_duplicates(factory_errors, "raffle-factory::ContractError")
    ok &= check_duplicates(catalog_errors, "raffle-shared::ProtocolError")
    ok &= check_catalog(instance_errors, catalog_errors, "raffle-instance::Error")
    ok &= check_catalog(
        factory_errors, catalog_errors, "raffle-factory::ContractError", factory=True
    )

    if not ok:
        print("\nCI check FAILED: error definitions and ProtocolError disagree.")
        sys.exit(1)

    print("CI check PASSED: no duplicate discriminants.")
    print("CI check PASSED: live error enums match ProtocolError.")
    sys.exit(0)


if __name__ == "__main__":
    main()
