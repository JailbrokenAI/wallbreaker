# Engine Capability Uplift — Tasks (Phase 3: Breakdown)

> Estimates in **iterations**. Status: `[ ]` not_started · `[~]` in_progress · `[x]` completed ·
> `[-]` blocked. Runs AFTER `roadmap-implementation`. Items C/F and judge-ensemble core are
> assumed **landed** (see the closed-items note); this spec builds on them.

## Closed by the prior (hardening) spec — do not re-do

- **[x] Item C — Supply-chain corpus pinning** (prior TG3): `library.lock.toml` + `corpus verify`
  + SHA fail-closed. *Carry-forward option, not a task: add GPG signature verify if a signed
  upstream tag becomes available.*
- **[x] Item F — Frontend decomposition** (prior TG4): Runs/Findings/Agent ≤400 LOC + CI
  line-count guard (regression already prevented).
- **[x] Item E — Judge-ensemble core** (prior TG7): `[[judge.ensemble]]`, majority vote, mean±1σ,
  `UNCERTAIN`. *Extended by TG4 below (calibration only).*

## Overview

8 new task groups. **TG1 (semantic embeddings) is foundational** — TG5, TG7, TG8 all depend on it.
**TG3 (family routing)** feeds TG5 and TG7. **TG2 (ToolContext)** is an independent refactor best
landed early so TG6's new agentic code is written against the decomposed context. **TG4** (judge
calibration) is independent and short. **TG8** is demand-gated (build only on a proven ceiling).

```
TG1 (A embeddings) ──┬─► TG5 (G bandit) ──► TG8 (J scale)
                     ├─► TG7 (I transfer)
TG3 (D family) ──────┴─► TG5, TG7
TG2 (B ToolContext) ─► (land early; TG6 builds on it)
TG4 (E calibration) ─► independent
TG6 (H agentic) ─────► independent (prefers TG2 first)
```

## Dependencies

- TG1 → TG5, TG7, TG8
- TG3 → TG5, TG7
- TG5 → TG8
- TG2 → TG6 (soft: write H against decomposed ctx)
- TG4, independent · TG8 gated on single-machine-ceiling evidence

## Parallelization

- **2 engineers:** Eng A on the retrieval/scheduling spine (TG1 → TG3 → TG5 → TG7 → TG8). Eng B on
  TG2 (refactor) → TG6 (agentic) → TG4 (calibration), all independent of the spine.
- **Sync point:** after TG1 + TG3, review the arm/embedding data model before TG5 and TG7 both
  build on it.
- Estimated: **~11–12 iterations sequential / ~7 with 2 engineers**. TG8 excluded from the base
  estimate (demand-gated).

---

## Task Group 1 — Pluggable Strategy Embeddings (item A)  ·  foundational · Priority 1

**Est: 1.5 iterations**

### Implementation
- [ ] 1.1 Add `strategy_embeddings` config (`bm25|openai|local|bow`, default `bm25`); make `embed()`
  dispatch over the backend. `cosine()` + `retrieve*()` untouched. *(R-A1)*
- [ ] 1.2 Implement the `bm25` lexical scorer (pure Python) as the no-config default; keep `bow` as
  a legacy option.
- [ ] 1.3 Implement `openai` (`text-embedding-3-small`) and `local` (ONNX sentence-transformer)
  dense backends; persist vector + `embedding_model` tag on the row. *(R-A3)*
- [ ] 1.4 Lazy re-embed: on retrieve, rows whose `embedding_model` ≠ active backend (incl. legacy
  untagged) are re-embedded and rewritten atomically; never dropped. *(R-A2)*

### Tier 1 — Focused
- [ ] 1.5 **Retrieval quality:** insert 5 distinct-description strategies; each description query
  returns its record in the top-2, for every backend. *(R-A4)*
- [ ] 1.6 No-config default (`bm25`) ≥ old `bow` baseline on the quality fixture (positive control).

### Tier 2 — PBT
- [ ] 1.7 SP-DI1 `test_self_retrieval_rank1`: ∀ stored strategy, retrieving its own description
  returns it rank-1 (per active backend).
- [ ] 1.8 SP-DI2 `test_row_roundtrip_reembed`: save→load preserves all rows; a backend switch
  re-embeds without losing or duplicating rows.

### Security/Correctness Readiness
- [ ] 1.9 Default path makes no network call. 1.10 Legacy library loads. 1.11 Backend recorded per
  row for reproducibility.

---

## Task Group 2 — ToolContext Decomposition (item B)  ·  land early · Priority 4

**Est: 2 iterations**

### Implementation (delegation only — zero signature changes)
- [ ] 2.1 Add `EngagementContext` + `IOContext` dataclasses. *(R-B1)*
- [ ] 2.2 `ToolContext` holds `config, cwd, judge_endpoint, confine_reads` + the two sub-contexts;
  every prior field is a delegating property. *(R-B1)*
- [ ] 2.3 `emit()`/`run()`/`record_verdict()` delegate to `IOContext`/`EngagementContext`; all ~80
  call sites unchanged. *(R-B2)*

### Tier 1 — Focused
- [ ] 2.4 Full existing suite passes unchanged (the parity gate). 2.5 A tool reading e.g.
  `ctx.current_objective` and `ctx.progress` still works via delegation.

### Tier 2 — PBT
- [ ] 2.6 SP-DI5 `test_context_delegation_parity`: for any field assignment via the envelope, the
  value read back through the delegating property equals the value on the sub-context.

### Readiness
- [ ] 2.7 No tool file edited for signatures. 2.8 New tools (TG6) can take `EngagementContext`
  directly if they choose.

---

## Task Group 3 — Target-Family Routing (item D)  ·  Priority 5

**Est: 1.5 iterations**

### Implementation
- [ ] 3.1 `classify_family(model) -> str` (total, deterministic, never raises) over
  openai/anthropic/google/deepseek/meta/other; set at `/target`. *(R-D1)*
- [ ] 3.2 Wire the family tag into the existing `ContextualBandit`/`context_key(family, category)`;
  seed per-family priors from CHANGELOG ASR data. *(R-D2)*
- [ ] 3.3 `/stats` "best technique by family". *(R-D3)*

### Tier 1 — Focused
- [ ] 3.4 Known model strings map to the expected family (table test incl. `deepseek/deepseek-chat`,
  `anthropic/claude-4`, `gpt-5`, `meta-llama/*`).

### Tier 2 — PBT
- [ ] 3.5 SP-IV1 `test_family_classifier_total`: ∀ string (incl. empty/garbage/unicode) →
  exactly one family, deterministic, no exception.

### Readiness
- [ ] 3.6 Unknown → `other`, never a crash. 3.7 Family seeding never worse than uniform (falls back
  to uniform when no prior).

---

## Task Group 4 — Judge-Ensemble Calibration (item E, build-upon)  ·  Priority 3

**Est: 1 iteration**

### Implementation (extends the delivered ensemble)
- [ ] 4.1 `judge_selftest` fires the ensemble across the 20 calibration fixtures; compute κ /
  per-member disagreement rate. *(R-E1)*
- [ ] 4.2 Non-zero exit + alert if any member disagrees with the majority on >20% of fixtures. *(R-E2)*

### Tier 1 — Focused
- [ ] 4.3 A deliberately-miscalibrated stub judge trips the >20% alert (negative control). 4.4 A
  well-behaved ensemble passes.

### Readiness
- [ ] 4.5 Single-judge default unaffected when no ensemble configured.

---

## Task Group 5 — Multi-Objective Campaign Bandit (item G)  ·  after TG1, TG3 · Priority 7

**Est: 3 iterations**

### Implementation (extends `_bandit.py`)
- [ ] 5.1 Widen arm → `(technique, transform_chain, behavior_category)`; Beta `(α,β)` per arm per
  family, reusing `Bandit.thompson_select`. *(R-G1)*
- [ ] 5.2 Campaign step: Thompson-sample, fire top arm, update on verdict. *(R-G2)*
- [ ] 5.3 Persist arm posteriors to `.wallbreaker_state.json` (atomic), resume across sessions. *(R-G3)*
- [ ] 5.4 Regret curve in `/stats`; `campaign --bandit-arms N --budget M`. *(R-G4)*

### Tier 1 — Focused
- [ ] 5.5 Regret curve beats a random-arm baseline on a seeded synthetic reward table.
- [ ] 5.6 Posterior resume: kill mid-campaign, resume, α/β intact.

### Tier 2 — PBT
- [ ] 5.7 SP-C1 `test_bandit_registered_arms_only`: `select`/`thompson_select` only ever return a
  registered arm; α,β ≥ 1 after any update sequence.
- [ ] 5.8 SP-DI3 `test_arm_posterior_roundtrip`: save→load preserves every arm's (α,β,n).

### Readiness
- [ ] 5.9 Concurrent arm fires still close clients via `provider_scope()`. 5.10 Grid-sweep still
  available for exhaustive coverage.

---

## Task Group 6 — Agentic Attack Surface Completion (item H)  ·  prefers TG2 · Priority 8

**Est: 4 iterations**  (largest group — 4 sub-surfaces)

### Implementation
- [ ] 6.1 `rag_poison`: PoisonedRAG injection bank (PDF/markdown/html-comment/white-text) + exfil
  grader (markdown-image beacon / keyword track) → separate `exfil` verdict. *(R-H1)*
- [ ] 6.2 `memory_poison`: MINJA inject→persist→trigger loop across a session boundary. *(R-H2)*
- [ ] 6.3 `agentharm`: tool schema + multi-question binary rubric grader (call? args? downstream?),
  monotonic score. *(R-H3)*
- [ ] 6.4 AgentDojo integration → coverage matrix (injection × task × ASR). *(R-H4)*

### Tier 1 — Focused
- [ ] 6.5 Exfil grader TP/FP fixtures. 6.6 Agentharm rubric fixtures (benign call vs. harmful call).
- [ ] 6.7 AgentDojo matrix shape on a sample task set.

### Tier 2 — PBT
- [ ] 6.8 SP-IV2 `test_agentharm_rubric_monotone`: adding a harmful checklist item never lowers the
  score; the grader is a pure function of the checklist.

### Readiness
- [ ] 6.9 All agentic artifacts to gitignored `wb_runs/`/`wb_artifacts/`. 6.10 Authorized-use
  doctrine unchanged. 6.11 Written against the decomposed `EngagementContext` (post-TG2).

---

## Task Group 7 — Cross-Family Transfer Learning (item I)  ·  after TG1, TG3 · Priority 9

**Est: 2.5 iterations**

### Implementation
- [ ] 7.1 `family` tag on every library row; cold-start retrieves top-5 same-family before live
  probes. *(R-I1)*
- [ ] 7.2 `transfer_score` (origin / same-family / cross-family wins), non-negative; bounded,
  monotone retrieval bonus. *(R-I2)*
- [ ] 7.3 `leaderboard --cross-family`: battery across ≥3 profiles → transfer matrix. *(R-I3)*

### Tier 1 — Focused
- [ ] 7.4 Held-out target: same-family retrieval improves cold-start ASR vs. no-retrieval baseline.
- [ ] 7.5 Cross-family matrix shape + symmetry sanity.

### Tier 2 — PBT
- [ ] 7.6 SP-DI4 `test_transfer_score_conservation`: components non-negative; bonus monotonic
  non-decreasing in transfer score; bounded.

### Readiness
- [ ] 7.7 Builds on TG1 embeddings + TG3 family tags (no new embedding path). 7.8 Anonymized export
  path for the transfer matrix (research contribution, opt-in).

---

## Task Group 8 — Distributed Campaign Infrastructure (item J)  ·  demand-gated · Priority 10

**Est: 4–6 iterations · build only on a demonstrated single-machine ceiling**

### Implementation
- [ ] 8.1 Pluggable strategy backend `jsonl|sqlite|postgres`; FAISS/pgvector index past 10k. *(R-J1)*
- [ ] 8.2 Work-queue (SQLite default, Redis optional) + `wallbreaker worker`; dashboard →
  controller. *(R-J2)*
- [ ] 8.3 Token-bucket per (provider, minute) + backpressure. *(R-J3)*
- [ ] 8.4 Worker authorized-target guard. *(R-J4)*

### Tier 1 — Focused
- [ ] 8.5 Backend parity: retrieve API returns identical results across jsonl/sqlite on a fixture
  library. 8.6 Two workers drain a queue without double-executing a task.

### Tier 2 — PBT
- [ ] 8.7 SP-RC1 `test_token_bucket_never_exceeds` (stateful/async): peak in-flight per provider ≤
  configured rate under generated request interleavings.
- [ ] 8.8 SP-AC1 `test_worker_rejects_unauthorized_target`: a task targeting a model outside the
  worker's authorized set is refused, no side effect.

### Readiness
- [ ] 8.9 Single-team default needs no external services (SQLite). 8.10 Access-control posture from
  the hardening spec carried into the worker tier.

---

## Roll-Up

| TG | Item | Iterations | New PBT props | Depends on | Priority |
|----|------|-----------|---------------|------------|----------|
| 1 | A embeddings | 1.5 | 2 (SP-DI1/DI2) | — | 1 |
| 4 | E calibration | 1 | 0 (Tier-1) | prior TG7 (ensemble) | 3 |
| 2 | B ToolContext | 2 | 1 (SP-DI5) | — | 4 |
| 3 | D family routing | 1.5 | 1 (SP-IV1) | — | 5 |
| 5 | G bandit | 3 | 2 (SP-C1/DI3) | 1, 3 | 7 |
| 6 | H agentic | 4 | 1 (SP-IV2) | 2 (soft) | 8 |
| 7 | I transfer | 2.5 | 1 (SP-DI4) | 1, 3 | 9 |
| 8 | J scale | 4–6 | 2 (SP-RC1/AC1) | 1, 5 | 10 |

**Base total (TG1–7):** ~11.5 iterations sequential / ~7 with 2 engineers · **8 new PBT
properties** across SP-DI/IV/C/RC/AC. TG8 excluded (demand-gated). Items C/F/E-core inherited from
the hardening spec.
