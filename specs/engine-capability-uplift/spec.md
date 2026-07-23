# Engine Capability Uplift — Specification (Phase 2: Write)

> Scannable spec, no implementation code. Derived from `planning/requirements.md`. Runs AFTER the
> `roadmap-implementation` (hardening) spec. Items C, F, and the judge-ensemble core are already
> delivered there and are built upon, not re-specified. Security/correctness-critical requirements
> carry a Security Property number (SP-n) validated in `pbt-properties.py`.

## Goal

Raise measured ASR and query-efficiency by making strategy retrieval semantic (A), scheduling
target-family- and arm-aware (D, G), the agentic surfaces first-class (H), and wins
transferable across families (I) — with a clean pluggable path to scale (J) — while decomposing
the `ToolContext` god-object (B) so the growth doesn't calcify, and closing the judge-ensemble
calibration follow-up (E-carry). Every capability change is guarded by a correctness PBT plus a
retrieval/regression quality test.

## User Stories

- **As a red-teamer resuming a campaign on a new model**, I want proven strategies from the same
  family surfaced before any live probe, so I don't cold-start from scratch every time.
- **As a red-teamer running a long campaign**, I want budget concentrated on the technique-behavior
  arms with the highest marginal payoff, and a regret curve that shows me it's working.
- **As an operator testing an agentic deployment**, I want real RAG/memory/tool-call attacks with
  an exfil grader, not stubs, so my coverage matches how the target is actually deployed.
- **As a maintainer**, I want to add new tools without threading yet another field through a
  13-field context object.
- **As anyone reporting ASR**, I want the ensemble's inter-judge agreement calibrated so a
  low-agreement verdict is flagged before it pollutes the numbers.

## Workstream Requirements

### TG1 — Pluggable Strategy Embeddings (item A)  ·  foundational

- **R-A1** Introduce a `strategy_embeddings` config setting: `"bm25" | "openai" | "local" | "bow"`.
  Default (no config) = `"bm25"` (pure-Python, zero-dep, zero-cost). `embed()` becomes a dispatch
  over the selected backend; `cosine()` and the three `retrieve*` methods are unchanged. *(SP-DI1)*
- **R-A2** Each stored strategy row gains an `embedding_model` tag. On retrieve, a row whose tag ≠
  the active backend is **lazily re-embedded** and rewritten; legacy rows with no tag load and
  re-embed, never drop. *(SP-DI2)*
- **R-A3** `bm25` is a lexical scorer over the description corpus (no vectors persisted); `openai`/
  `local` persist a dense vector + model tag. The retrieve API returns the same shape regardless of
  backend.
- **R-A4** Retrieval-quality gate: inserting 5 strategies with distinct descriptions, a query equal
  to each description returns that record in the **top-2**, for every backend. *(quality test)*

### TG2 — ToolContext Decomposition (item B)

- **R-B1** Extract `EngagementContext` (`current_objective`, `attacker_model`, `vault_enabled`,
  `target_thread`, `target_system`, `target_reasoning`) and `IOContext` (`progress`, `record`,
  `run_events`, `tool_logger`). `ToolContext` becomes a thin envelope: `config`, `cwd`,
  `judge_endpoint`, `confine_reads`, + the two sub-contexts.
- **R-B2** `ctx.emit()`, `ctx.run()`, `ctx.record_verdict()`, and every current field access remain
  as **delegating properties** — **zero tool signature changes**, full existing suite green. *(SP-DI5 parity)*

### TG3 — Target-Family Routing (item D)

- **R-D1** A pure `classify_family(model: str) -> str` maps model strings to one of the fixed
  families (`openai/anthropic/google/deepseek/meta/other`) — total, deterministic, never raises.
  Set the family tag at `/target` time. *(SP-IV1)*
- **R-D2** Per-family technique rankings persist in `.wallbreaker_state.json` via the existing
  `ContextualBandit`/`context_key(family, category)`; seed with empirical priors from the CHANGELOG
  ASR data instead of a uniform prior.
- **R-D3** `/stats` surfaces "best technique by family". Convergence on a new same-family target is
  measurably faster than a cold uniform prior (recorded in the regret comparison from TG5).

### TG4 — Judge-Ensemble Calibration (item E, build-upon)

- **R-E1** Extend `judge_selftest` to fire the *ensemble* (delivered in the hardening spec) across
  the calibration fixtures and compute inter-judge agreement (κ / per-class disagreement rate).
- **R-E2** Alert (non-zero self-test exit) if **any** ensemble member disagrees with the majority on
  **>20%** of fixtures — a miscalibrated or family-biased judge is caught before it grades a run.

### TG5 — Multi-Objective Campaign Bandit (item G)  ·  after TG1, TG3

- **R-G1** Widen the bandit arm from a technique to a `(technique, transform_chain,
  behavior_category)` tuple; maintain Beta `(α, β)` per arm **per target-family** on top of the
  existing `Bandit.thompson_select`. *(SP-C1)*
- **R-G2** Each campaign step Thompson-samples the arm posterior, fires the top arm, updates `(α,β)`
  on the verdict. `select`/`thompson_select` may only ever return a **registered** arm. *(SP-C1)*
- **R-G3** Arm posteriors persist to `.wallbreaker_state.json` (atomic) and resume across sessions
  with no loss. *(SP-DI3)*
- **R-G4** `/stats` gains a **regret curve**: cumulative ASR vs. a random-arm baseline as a function
  of budget spent. `campaign --bandit-arms N --budget M` is the primary interface; grid-sweep stays
  for exhaustive coverage.

### TG6 — Agentic Attack Surface Completion (item H)

- **R-H1** `rag_poison`: a PoisonedRAG injection bank across carrier formats (PDF, markdown, HTML
  comment, white-text CSS) + an **exfil grader** (EchoLeak markdown-image beacon / keyword track):
  a separate `exfil` verdict = did the agent surface the poisoned content downstream? *(SP-IV2)*
- **R-H2** `memory_poison`: the MINJA persistence loop — inject once, verify persistence across a
  session boundary, trigger on a subsequent clean session (targets exposing a memory API).
- **R-H3** `agentharm`: give the target a tool schema; grade with a **multi-question binary rubric**
  (did it call the tool? with what argument? what downstream action?) not a single holistic score.
  The rubric-to-score function is monotonic in harmful checklist items. *(SP-IV2)*
- **R-H4** AgentDojo integration reporting a structured coverage matrix (injection type × task
  category × ASR).

### TG7 — Cross-Family Transfer Learning (item I)  ·  after TG1, TG3

- **R-I1** Every library row carries a `family` tag alongside the target model. Cold-start on a new
  target retrieves the top-5 same-family strategies before any live probe. *(builds on TG1 + TG3)*
- **R-I2** A per-strategy `transfer_score` tracks (wins on origin, wins transferred same-family,
  wins transferred cross-family); all components non-negative; a high transfer score grants a
  bounded retrieval bonus that is **monotonic** in the score. *(SP-DI4)*
- **R-I3** `leaderboard --cross-family` runs one battery across ≥3 profiles and reports a transfer
  matrix (winning technique on A → its ASR on B).

### TG8 — Distributed Campaign Infrastructure (item J)  ·  after TG1, TG5 · demand-gated

- **R-J1** Pluggable strategy backend: `jsonl` (current) | `sqlite` | `postgres`; dense vectors
  indexed (FAISS/pgvector) past 10k entries. Retrieve API unchanged across backends.
- **R-J2** Campaign-level parallelism moves from in-process `gather_capped` to a lightweight
  work-queue (SQLite default, Redis optional); `wallbreaker worker` consumes tasks, writes results
  back; the dashboard becomes a campaign controller.
- **R-J3** A **token-bucket per (provider, minute)** queues excess requests with backpressure to the
  scheduler; peak in-flight per provider never exceeds the configured rate. *(SP-RC1)*
- **R-J4** A worker only executes tasks against targets in its authorized set (carries forward the
  hardening spec's access-control posture into the distributed tier). *(SP-AC1)*

## PBT Validation Strategy

### Property-Based (Hypothesis) — correctness/security-critical

| Property | Component | SP | Task |
|---|---|---|---|
| Self-retrieval rank-1 per backend | `strategy_lib` embed dispatch | SP-DI1 | TG1 |
| Row round-trip + lazy re-embed preserves rows | `StrategyLibrary` load/save | SP-DI2 | TG1 |
| ToolContext delegation parity | `registry.ToolContext` | SP-DI5 | TG2 |
| Family classifier totality | `classify_family` | SP-IV1 | TG3 |
| Bandit selects only registered arms | `_bandit` widened arms | SP-C1 | TG5 |
| Arm-posterior persistence round-trip | `BanditStore` | SP-DI3 | TG5 |
| Agentharm rubric monotonic in harm | `agentharm` grader | SP-IV2 | TG6 |
| Transfer-score conservation + monotone bonus | `strategy_lib` transfer | SP-DI4 | TG7 |
| Token-bucket never exceeds rate (stateful) | `campaign` rate limiter | SP-RC1 | TG8 |
| Worker rejects out-of-scope target | `worker` guard | SP-AC1 | TG8 |

### Focused (deterministic) — Tier 1

- Retrieval quality top-2 (A, R-A4), regret-curve beats random baseline (G), exfil-grader
  true/false-positive fixtures (H), cross-family matrix shape (I), judge_selftest >20% alert (E).

### Security/Correctness Properties (5 mandated categories, mapped to real functions)

1. **SP-IV Input Validation** → `classify_family` (total function), `agentharm` rubric grader.
2. **SP-DI Data Integrity** → embedding self-retrieval + row round-trip + lazy re-embed;
   bandit-posterior persistence; transfer-score conservation; ToolContext delegation parity.
3. **SP-C Correctness/Concurrency** → bandit only returns registered arms; Thompson update keeps
   `α,β ≥ 1`.
4. **SP-RC Rate Limiting** → token-bucket peak ≤ configured provider rate (stateful PBT).
5. **SP-AC Access Control** → distributed worker executes only authorized targets (re-engages the
   hardening spec's posture at the new tier).

## Out of Scope

- Items **C, F, E-core** — delivered by the hardening spec; only E-calibration is in scope here.
- Judging *rubric* redesign (what counts as harmful) — TG4 only calibrates ensemble agreement.
- New attack *techniques* beyond completing the existing agentic stubs (H fills stubs; it does not
  invent new single-turn attacks).
- Speculative distributed build — TG8 is gated on a demonstrated single-machine ceiling.
- Any change to the responsible-use / authorization posture.

## Quality Gates

- **Gate 2:** all Tier-1 tests green (retrieval top-2, regret-beats-random, exfil fixtures,
  cross-family shape, self-test alert); full pre-existing suite still green after TG2 refactor.
- **Gate 3:** every SP-n property green, no open counterexample, each meets its `max_examples`
  floor; positive controls asserted (no-config default ≥ BoW baseline; no unregistered arm; no
  rate breach).
- **Gate 4:** integration properties (family-seeded bandit converges faster than uniform;
  cross-family retrieval improves cold-start ASR on a held-out target) green; `security-audit-
  prep.md` updated with the new correctness properties.
