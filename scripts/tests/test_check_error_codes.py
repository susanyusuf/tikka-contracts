"""Unit tests for scripts/check_error_codes.py.

Covers the parsing layer, the duplicate detection (including the
duplicate-discriminant regression the checker exists to catch), the
catalog comparison, and the script's process exit codes on fixture
repositories.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Make the scripts package importable without installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from check_error_codes import (
    check_catalog,
    check_duplicates,
    parse_error_enum,
)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "check_error_codes.py"


def _write_enum(tmp_path: Path, enum_name: str, body: str) -> Path:
    """Write a minimal Rust source file containing one enum and return its path."""
    src = tmp_path / "lib.rs"
    src.write_text(
        textwrap.dedent(f"""\
        #[contracterror]
        #[derive(Copy, Clone)]
        pub enum {enum_name} {{
        {body}
        }}
        """),
        encoding="utf-8",
    )
    return src


def _write_fixture_repo(
    root: Path,
    instance_body: str,
    factory_body: str,
    catalog_body: str,
) -> Path:
    """Create a minimal repo tree the script can run against."""
    instance = root / "contracts" / "raffle-instance" / "src" / "lib.rs"
    factory = root / "contracts" / "raffle-factory" / "src" / "lib.rs"
    catalog = root / "contracts" / "raffle-shared" / "src" / "errors.rs"
    for path in (instance, factory, catalog):
        path.parent.mkdir(parents=True, exist_ok=True)
    instance.write_text(f"pub enum Error {{\n{instance_body}\n}}\n", encoding="utf-8")
    factory.write_text(f"pub enum ContractError {{\n{factory_body}\n}}\n", encoding="utf-8")
    catalog.write_text(f"pub enum ProtocolError {{\n{catalog_body}\n}}\n", encoding="utf-8")
    scripts_dir = root / "scripts"
    scripts_dir.mkdir()
    shutil.copy(SCRIPT_PATH, scripts_dir / "check_error_codes.py")
    return scripts_dir / "check_error_codes.py"


def _run_script(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# parse_error_enum
# ---------------------------------------------------------------------------


class TestParseErrorEnum:
    def test_parses_code_name_and_factory_original(self, tmp_path: Path) -> None:
        src = _write_enum(
            tmp_path,
            "ProtocolError",
            "    FactoryAlpha = 200, // factory original: 1\n    Alpha = 7,",
        )
        result = parse_error_enum(src, "ProtocolError")
        assert result == [(200, "FactoryAlpha", 1), (7, "Alpha", None)]

    def test_missing_enum_raises_value_error(self, tmp_path: Path) -> None:
        src = tmp_path / "lib.rs"
        src.write_text("pub enum OtherName { A = 1, }", encoding="utf-8")
        with pytest.raises(ValueError, match="Could not find enum Error"):
            parse_error_enum(src, "Error")

    def test_doc_comment_code_text_is_not_a_variant(self, tmp_path: Path) -> None:
        src = _write_enum(
            tmp_path,
            "Error",
            "    /// Instance-only code 100 for Foo.\n    Foo = 100,",
        )
        assert parse_error_enum(src, "Error") == [(100, "Foo", None)]

    def test_variant_without_discriminant_is_skipped(self, tmp_path: Path) -> None:
        src = _write_enum(tmp_path, "Error", "    Valid = 1,\n    NoCode,\n    Also = 2,")
        names = [name for _, name, _ in parse_error_enum(src, "Error")]
        assert names == ["Valid", "Also"]


# ---------------------------------------------------------------------------
# check_duplicates
# ---------------------------------------------------------------------------


class TestCheckDuplicates:
    def test_duplicate_discriminant_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        errors = [
            (67, "CancelTimelockActive", None),
            (67, "ExceedsMaxTicketsPerAddress", None),
        ]
        assert check_duplicates(errors, "raffle-instance::Error") is False
        assert "Duplicate discriminant 67" in capsys.readouterr().out

    def test_duplicate_variant_name_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        errors = [(1, "Alpha", None), (2, "Alpha", None)]
        assert check_duplicates(errors, "Error") is False
        assert "Duplicate variant Alpha" in capsys.readouterr().out

    def test_unique_codes_pass(self) -> None:
        errors = [(1, "Alpha", None), (2, "Beta", None)]
        assert check_duplicates(errors, "Error") is True


# ---------------------------------------------------------------------------
# check_catalog
# ---------------------------------------------------------------------------


class TestCheckCatalog:
    def test_matching_codes_pass(self) -> None:
        live = [(7, "Foo", None)]
        catalog = [(7, "Foo", None)]
        assert check_catalog(live, catalog, "raffle-instance::Error") is True

    def test_missing_catalog_entry_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert (
            check_catalog([(7, "NotThere", None)], [(1, "Present", None)], "raffle-instance::Error")
            is False
        )
        assert "missing from ProtocolError" in capsys.readouterr().out

    def test_mismatched_code_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert (
            check_catalog([(7, "Foo", None)], [(8, "Foo", None)], "raffle-instance::Error") is False
        )
        assert "uses 8" in capsys.readouterr().out

    def test_factory_compares_recorded_abi_code(self) -> None:
        live = [(11, "AdminTransferPending", None)]
        catalog = [(205, "FactoryAdminTransferPending", 11)]
        assert check_catalog(live, catalog, "raffle-factory::ContractError", factory=True) is True

    def test_factory_abi_mismatch_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        live = [(11, "AdminTransferPending", None)]
        catalog = [(205, "FactoryAdminTransferPending", 12)]
        assert check_catalog(live, catalog, "raffle-factory::ContractError", factory=True) is False
        assert "maps to factory ABI code 12" in capsys.readouterr().out

    def test_factory_code_must_live_in_200_range(self, capsys: pytest.CaptureFixture[str]) -> None:
        live = [(11, "AdminTransferPending", None)]
        catalog = [(11, "FactoryAdminTransferPending", 11)]
        assert check_catalog(live, catalog, "raffle-factory::ContractError", factory=True) is False
        assert "200-299" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# End-to-end: process exit codes on fixture repositories
# ---------------------------------------------------------------------------


class TestScriptExitCodes:
    def test_exits_nonzero_on_duplicate_discriminant(self, tmp_path: Path) -> None:
        script = _write_fixture_repo(
            tmp_path,
            instance_body="    First = 67,\n    Second = 67,",
            factory_body="    Alpha = 1,",
            catalog_body="    First = 67,\n    Second = 67,",
        )
        result = _run_script(script)
        assert result.returncode == 1
        assert "Duplicate discriminant 67" in result.stdout

    def test_exits_nonzero_when_catalog_disagrees(self, tmp_path: Path) -> None:
        script = _write_fixture_repo(
            tmp_path,
            instance_body="    First = 1,",
            factory_body="    Alpha = 1,",
            catalog_body="    First = 2,",
        )
        result = _run_script(script)
        assert result.returncode == 1
        assert "uses 2" in result.stdout

    def test_exits_zero_when_consistent(self, tmp_path: Path) -> None:
        script = _write_fixture_repo(
            tmp_path,
            instance_body="    First = 1,",
            factory_body="    Alpha = 1,",
            catalog_body="    First = 1,\n    FactoryAlpha = 200, // factory original: 1",
        )
        result = _run_script(script)
        assert result.returncode == 0
        assert "CI check PASSED" in result.stdout

    def test_exits_nonzero_when_enum_missing(self, tmp_path: Path) -> None:
        script = _write_fixture_repo(
            tmp_path,
            instance_body="    First = 1,",
            factory_body="    Alpha = 1,",
            catalog_body="    First = 1,",
        )
        # Break the factory enum name so the parser cannot find it.
        (script.parent.parent / "contracts" / "raffle-factory" / "src" / "lib.rs").write_text(
            "pub enum SomethingElse { Alpha = 1, }\n", encoding="utf-8"
        )
        result = _run_script(script)
        assert result.returncode == 1
        assert "Could not find enum ContractError" in result.stdout
