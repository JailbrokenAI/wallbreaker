# Completion Report — roadmap-implementation

> Provenance note: the producer executed this spec across `53c9ca2` (TG1–TG7), `9ec12b0`
> (round-1 revision), and `cfb35cc` (CI cold-checkout follow-up). This report was compiled
> from those delivered commits and the independent PM validation (`verdict.md`) — every
> "Evidence" line below was re-verified by the validator (fresh clone, full `pytest`, CLI
> exercised), not taken on the producer's word. It closes the §C handshake loop that was
> previously served by informal summaries.

## Header
- spec_id: roadmap-implementation
- producer: claude-sonnet (rial1)
- compiled_by: claude-opus-4-8 (PM/validator) from verified evidence
- started: 2026-07-22
- completed: 2026-07-23 (round-1 revision + CI follow-up same day)
- spec_version: 1 (artifacts under `specs/roadmap-implementation/`)
- delivered_commits: `53c9ca2`, `9ec12b0`, `cfb35cc` (on `main`; tip `6e7ac8b`)

## Artifacts Produced
- `wallbreaker/tools/egress_guard.py`: fail-closed pinned-transport self-check + two-tier policy docstring (A/B).
- `pyproject.toml`: httpx pinned `>=0.27,<0.29` (A).
- `.github/workflows/redteam-gate.yml`: CI gate — PBT + httpx matrix + `-W error::ResourceWarning` (E).
- `tests/` — 31 `xfail` / skips for pre-existing corpus failures; `test_tg3_corpus.py`, `test_tg5_harden.py`, `test_tg7_trust.py`, plus additions to `tests/pbt/test_security_properties.py` (8 security/correctness properties).
- `library.lock.toml` + `wallbreaker/tools/parsel_engine.py` (`verify_corpus_sha`, `load_corpus_with_pin_check`) + `wallbreaker/cli.py` (`corpus verify`) (D).
- Frontend: `RunDetailView.tsx`, `RunExpandedRow.tsx`, `FindingExpanded.tsx`, `AgentTranscript.tsx` + `check:line-counts` npm script; `Runs/Findings/Agent.tsx` reduced ≤400 (F).
- `agent_dashboard_harden/` package (`__init__.py` re-exports, `pbt_fixtures.py`, `README.md`) (G).
- `UPSTREAM-PR.md` + apply-check script (C).
- `wallbreaker/findings_log.py` (Ed25519 signed log) + `wallbreaker/judging.py` (`run_ensemble`/`run_ensemble_probe`) (H).
- `CHANGELOG.md` roadmap-implementation entry.
- CI follow-up: `tests/test_seed_sweep.py` corpus skip guard; `wallbreaker/prompts.py` handle-leak fix.

## Acceptance Criteria Self-Check

- **R-A1** — `make_pinned_transport` fails closed on missing httpx internals.
  - Claim: met. Evidence: `tests/pbt/test_security_properties.py::test_pinned_transport_fail_closed_on_missing_attr` + `test_make_pinned_transport_returns_pinned_backend` (green; PM re-ran).
- **R-A2** — httpx pinned + matrix-tested.
  - Claim: met. Evidence: `pyproject.toml` range; `redteam-gate.yml` matrix.
- **R-B1** — two-tier egress policy (advisory `check_url` can't widen enforced `PinnedEgressBackend`).
  - Claim: met. Evidence: `egress_guard.py` docstring + PBT egress properties.
- **R-D1** — corpus SHA pin, fail-closed on mismatch/unresolved.
  - Claim: met (see Deviation 1 on pin coverage). Evidence: `test_tg3_corpus.py` (6 tests); `SP-4` property; `corpus verify` output `UltraBr3aks/ZetaLib=OK`, 3 online-only=`UNRESOLVED` (PM-run).
- **R-D2** — `wallbreaker corpus verify` CLI, non-zero on drift.
  - Claim: met. Evidence: CLI exercised by PM; `cli.py:_run_corpus_verify`.
- **R-E1** — clean gated `pytest -q` baseline.
  - Claim: met. Evidence: warm `1191 passed / 39 skipped / 31 xfailed`, exit 0 (PM reproduced `1190`+`stego`).
- **R-E2** — PBT + ResourceWarning gate required in CI.
  - Claim: met. Evidence: `redteam-gate.yml`.
- **R-F1** — `Runs/Findings/Agent.tsx` ≤400 each, extracted children ≤400, in the guard.
  - Claim: met. Evidence: line-count guard run by PM — Runs 295 / Findings 373 / Agent 328 / RunDetailView 364 / RunExpandedRow 157.
- **R-F2** — manual screen-reader pass.
  - Claim: partially met (Deviation 2). Evidence: code patterns + jest-axe clean; manual NVDA/VoiceOver pass recorded as residual.
- **R-G1** — `agent_dashboard_harden` re-exports with zero behavior change.
  - Claim: met. Evidence: `test_tg5_harden.py` asserts same-object re-exports + middleware still blocks unauth/cross-site (`SP-1`, `SP-5`).
- **R-G2** — 5 PBT categories shipped as parameterizable fixtures.
  - Claim: met. Evidence: `agent_dashboard_harden/pbt_fixtures.py`; factory tests in `test_tg5_harden.py`.
- **R-C1** — upstream PR series prepared.
  - Claim: met, re-scoped. Evidence: `UPSTREAM-PR.md` (now covers audit remediation + roadmap-implementation; see Deviation 3).
- **R-H1** — Ed25519 signed findings log, tamper-evident, private key never exported.
  - Claim: met. Evidence: `test_tg7_trust.py` (verify accepts valid / rejects tampered; `test_sign_entry_does_not_embed_private_key`); `SP-3`.
- **R-H2** — opt-in judge ensemble (≤3), majority vote, mean±1σ, `UNCERTAIN`, default unchanged.
  - Claim: met. Evidence: `test_tg7_trust.py` ensemble tests; `judging.run_ensemble`.

## Interfaces Delivered
- `agent_dashboard_harden` — Location: `agent_dashboard_harden/__init__.py`. Shape: re-exports `SecurityMiddleware`, `ensure_launch_token`, `origin_is_same_site`, `token_file_path`, `check_url`, `EgressBlocked`, `PinnedEgressBackend`, `make_pinned_transport`, `build_dashboard_registry`. Behavior: identical to in-repo originals (same objects).
- `wallbreaker.findings_log` — `sign_entry`/`verify_entry`/`generate_keypair`/`append_finding`/`load_findings`. Behavior: append-only Ed25519-signed JSONL; tamper → verify False.
- `wallbreaker corpus verify [--update]` (alias `parsel verify`) — reports pinned-vs-actual; exit non-zero on drift; loader fails closed.
- `wallbreaker.judging.run_ensemble` / `run_ensemble_probe` — opt-in multi-judge verdict; single-judge default unchanged.

## Known Deviations
1. **Corpus pins partial by design.** `library.lock.toml` carries real SHAs for the two locally-clonable corpora (`UltraBr3aks`, `ZetaLib`, verified to match clone HEADs); the three network-only corpora (`P4RS3LT0NGV3`, `L1B3RT4S`, `ENI`) remain `UNRESOLVED` until `corpus verify --update` runs with network. Fail-closed either way.
2. **R-F2 screen-reader pass** is code-pattern-verified + jest-axe-clean, but the manual NVDA/VoiceOver pass is a documented residual, not executed.
3. **R-C1 scope widened** (this task): the upstream PR now covers the audit remediation *and* the roadmap-implementation hardening, since both are on `main`. The prior `UPSTREAM-PR.md` caveat about `agent_dashboard_harden` not being on-branch no longer applies.
4. **CI cold-checkout follow-up** (`cfb35cc`): `test_collect_seeds_includes_gem_corpora` hard-failed on a corpus-less runner; a `skipif` guard (same Issue-2 pattern) was added post-validation, plus a `prompts.py` file-handle fix. Verified cold: `1175 passed / 55 skipped / 31 xfailed`, exit 0.

## State Management
### Progress Tracking
- Spec file: `specs/roadmap-implementation/spec.md` — all boxes checked: yes.
- Phase log: not maintained as a separate file; per-TG detail is in `PROGRESS.md` and the commit trail. ("All phases straightforward — checkmarks + PROGRESS sufficient.")

### Memory Bank
- `.agents/memory_bank/active/PROGRESS.md` — Action: appended. Content: 2026-07-23 entry, per-TG breakdown, commit SHAs, suite numbers. Verified: yes (operator-supplied).
- `.agents/memory_bank/active/current_focus.md` — Action: updated. Content: roadmap-implementation TG1–TG7 complete @ `53c9ca2`, revision @ `9ec12b0`, 5 issues resolved, P3.5 items flipped to DONE. Verified: yes (operator-supplied). Residual hygiene: resumption section still lists already-done Issues 1–4 and two stale state lines — advisory.

### Progress Entry
```markdown
### 2026-07-23
- **Implemented:** roadmap-implementation — TG1–TG7 (items A–H): egress de-fragilization, gated CI baseline, corpus pinning, frontend decomposition, hardening toolkit, upstream prep, signed log + judge ensemble. CI cold-checkout guard + prompts handle fix.
- **Decided:** upstream PR re-scoped to cover audit remediation + roadmap-implementation together; capability work deferred to a separate PR.
- **Blocked:** none.
- **Next:** upstream PR (this task) → then engine-capability-uplift (separate branch/PR, third-vendor producer/validator).
```

## Handoff Notes
- Warm test numbers require the gitignored `ZetaLib`/`UltraBr3aks` corpora present under `library/`; a cold checkout skips those tests (guarded) and still exits 0.
- Full suite needs the project `.venv` with `.[dev,dashboard,barcodes]` (+ `stego` for the one extra passing test that otherwise skips).
- PM verdict: **approved** — see `verdict.md` in this directory.
