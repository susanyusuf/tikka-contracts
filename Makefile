.PHONY: build check check-targets test test-doc lint fmt-check clippy orphan-check wasm-size \
        docs-errors docs-events shellcheck \
        ruff-lint ruff-fmt-check python-tests supply-chain \
        fuzz clean deploy-testnet deploy-mainnet verify reproducible \
        oracle-build oracle-test oracle-test-ci oracle-lint oracle-fmt-check oracle-typecheck \
        all ci

# ---------------------------------------------------------------------------
# Rust / contract targets
# ---------------------------------------------------------------------------

# `stellar contract build` targets wasm32v1-none — the same target the deploy
# scripts and CI use. Keep every build path going through it (issue #841); the
# artifact paths are defined once in scripts/common.sh.
build:
	stellar contract build

# Fast compile gate (mirrors the `check` CI job).
check:
	cargo check --workspace --all-targets --all-features --exclude raffle-fuzz

# Run all workspace unit + integration tests.
test:
	cargo test --workspace

# Run workspace doc-tests separately (cargo test --workspace does not run them).
test-doc:
	cargo test --workspace --doc

# fmt-check and clippy are split so each can be called independently; `lint`
# keeps the original convenience alias that runs both together.
fmt-check:
	cargo fmt --all -- --check

clippy:
	cargo clippy --all-targets --all-features -- -D warnings

# Derive fuzz targets from fuzz/Cargo.toml so this list never drifts from what
# is actually declared.  The shell snippet greps every [[bin]] name = "…" line,
# strips the surrounding quotes and whitespace, then joins the results.
FUZZ_TARGETS := $(shell grep -A1 '^\[\[bin\]\]' fuzz/Cargo.toml \
                  | grep 'name\s*=' \
                  | sed 's/.*name\s*=\s*"\([^"]*\)".*/\1/')
FUZZ_TIME ?= 300

fuzz:
	@for target in $(FUZZ_TARGETS); do \
		echo "==> fuzzing $target (${FUZZ_TIME}s)"; \
		cargo fuzz run $target -- -max_total_time=$(FUZZ_TIME); \
	done

# ---------------------------------------------------------------------------
# Deploy / utility
# ---------------------------------------------------------------------------

# Fail if anything that executes on clone, open or install has entered the
# tree: editor auto-run tasks, npm lifecycle scripts, font-shaped binaries.
supply-chain:
	python3 scripts/check_supply_chain.py

deploy-testnet:
	./scripts/deploy-testnet.sh

deploy-mainnet:
	./scripts/deploy-mainnet.sh

verify:
	./scripts/verify.sh

reproducible:
	./scripts/build-reproducible.sh

clean:
	cargo clean

# ---------------------------------------------------------------------------
# Check targets
#
# Every name in `.PHONY` — and every `make` target called from
# .github/workflows/ci.yml — must have a real recipe here: `make` treats a
# `.PHONY` name with no recipe as a no-op that always succeeds, so a missing
# recipe silently turns `make ci` green (issue #1173).
#
# The commands are the ones the workflow used to shell out to directly, so CI
# and a local `make ci` run the same thing (issue #1175).
# ---------------------------------------------------------------------------

# `lint` was always documented as "fmt-check and clippy together"; without a
# recipe, `all: lint test build` silently skipped both linters.
lint: fmt-check clippy

# Fails when a `.PHONY` name above loses its recipe. Keep this first in `ci:`.
check-targets:
	python3 scripts/check_make_targets.py

orphan-check:
	python3 scripts/check_orphan_modules.py

# 128 KB limit plus the per-binary baseline delta in `baselines/`. Set
# WASM_SIZE_REPORT to also write the human-readable PR report (CI does).
wasm-size:
	python3 scripts/check_wasm_sizes.py

# `--check` regenerates in memory and fails on any difference instead of
# rewriting the docs, which is what CI needs.
docs-errors:
	python3 scripts/generate_error_docs.py --check

docs-events:
	python3 scripts/generate_event_docs.py --check

shellcheck:
	shellcheck scripts/*.sh

ruff-lint:
	ruff check scripts

ruff-fmt-check:
	ruff format --check scripts

python-tests:
	python3 -m pytest scripts/tests

# ---------------------------------------------------------------------------
# Oracle service (Node/TypeScript) — the oracle_check CI job
# ---------------------------------------------------------------------------
oracle-build:
	cd oracle && npm run build

oracle-test:
	cd oracle && npm test

oracle-test-ci:
	cd oracle && npm run test:ci

oracle-lint:
	cd oracle && npm run lint

oracle-fmt-check:
	cd oracle && npm run format:check

oracle-typecheck:
	cd oracle && npm run typecheck

# ---------------------------------------------------------------------------
# Convenience aliases
# ---------------------------------------------------------------------------

# Original convenience target — kept for existing muscle memory.
all: lint test build

# ---------------------------------------------------------------------------
# ci — mirrors .github/workflows/ci.yml build_and_test + shellcheck +
#       oracle_check jobs exactly and in the same order.
#
# Run this before every push to catch CI failures locally.
#
# Steps omitted here because they cannot run without CI infrastructure:
#   - Rust/Node cache warm-up       (Swatinem/rust-cache, actions/setup-node)
#   - WASM size PR summary          (writes to $GITHUB_STEP_SUMMARY, PR-only)
#   - Coverage ratchet              (needs cargo-llvm-cov; run separately)
#   - Upload artifact steps
# ---------------------------------------------------------------------------
ci: check-targets check fmt-check orphan-check build wasm-size docs-errors docs-events \
    clippy test test-doc shellcheck \
    ruff-lint ruff-fmt-check python-tests supply-chain \
    oracle-fmt-check oracle-lint oracle-typecheck oracle-test-ci
