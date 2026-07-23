# Engine Capability Uplift — Requirements (Phase 1: Shape)

> Feature: **engine-capability-uplift** — implement the ASR/capability roadmap (items A–J) on the
> wallbreaker red-team engine. Sequenced to run **after** the `roadmap-implementation`
> (hardening) spec lands. Methodology: spec-architect, PBT gates, esoteric framing dropped.
> For authorized LLM red-teaming and safety evaluation only.

## 1. Problem Statement

The hardening spec made the tool safe to run; it did not make the tool *better at its job*. The
inherited engine has three compounding limitations:

1. **Strategy memory barely retrieves.** `strategy_lib.embed()` is a sha1 feature-hash
   bag-of-words over 256 buckets. Lexically-distinct-but-semantically-similar strategies score low
   cosine similarity, so proven tactics are not surfaced when they are relevant — the lifelong
   library's compounding value is throttled at the retrieval step.
2. **Scheduling is context-blind.** The campaign ladder applies one technique sequence to every
   target; the bandit is keyed only by `(target_model, category)`. Cross-target and per-family
   signal is discarded, so every new target cold-starts from a uniform prior.
3. **Whole surfaces are stubs.** The agentic tools (`rag_poison`, `memory_poison`, `agentharm`)
   are thin relative to the single-turn arsenal, exactly as agentic deployments become the
   dominant attack surface.

## 2. Goal (one sentence)

Raise measured ASR and query-efficiency by making strategy retrieval semantic, scheduling
target-family- and arm-aware, and the agentic surfaces first-class — each capability change
guarded by a data-integrity/correctness PBT and a retrieval/regression quality test.

## 3. Scope Note — Deliberate Expansion

Unlike the hardening spec, this work **modifies the inherited engine** (`strategy_lib.py`,
`_bandit.py`, `campaign.py`, `judging.py`, the agentic tools) that the fork previously left
untouched. That is an intentional widening of the fork's charter from "harden the tool" to
"advance the tool." It should be signalled to upstream so the capability work can be contributed
back or diverge deliberately, not accidentally.

## 4. Reconciliation with the `roadmap-implementation` spec (build-upon, don't duplicate)

Three roadmap items are **already delivered** by the hardening spec and are NOT re-specified here;
this spec builds on their landed state:

| This roadmap | Hardening-spec origin | Status entering this spec | This spec's action |
|---|---|---|---|
| **C — Supply-chain corpus pinning** | item D / TG3 (`library.lock.toml`, `corpus verify`, SHA fail-closed) | **Delivered** | Closed. Optional GPG-verify carry-forward noted in spec, not a task group. |
| **F — Frontend decomposition** | item F / TG4 (Runs/Findings/Agent ≤400 LOC + CI line guard) | **Delivered** | Closed. CI line-count guard already prevents regression. |
| **E — Judge ensemble (core)** | item H / TG7 (`[[judge.ensemble]]`, majority vote, mean±1σ, `UNCERTAIN`) | **Delivered** | **Build upon:** this spec adds only the *calibration* extension (inter-ensemble agreement in `judge_selftest`), which TG7 left as a follow-up. → TG4 here. |

Everything else (A, B, D, G, H, I, J) is new work owned by this spec.

## 5. Existing Code to Leverage (reuse before build)

- **`strategy_lib.py`** — `embed()`, `cosine()`, `retrieve()/retrieve_positive()/avoid_rules()`,
  `StrategyLibrary` (JSONL rows already carry an `embedding` field, tiers effective/promising/
  ineffective). Item A swaps the embedding source behind these existing methods; rows gain an
  `embedding_model` tag for forward-compat + lazy re-embed.
- **`tools/_bandit.py`** — **already has** `Bandit` (UCB `select`/`rank`, `thompson_select` with
  Beta α=reward+1/β=n−reward+1), `BanditStore` keyed by `_key(target_model, category)`,
  `ContextualBandit`, and `context_key(target_family, harm_category)`. Items D and G extend this,
  they do not reinvent it. The `target_family` dimension already exists in `context_key` — D wires
  a classifier into it; G widens the arm space.
- **`tools/campaign.py`** (364 LOC) — the ladder + coverage matrix. D and G plug the family
  classifier and the multi-objective arm selector in here.
- **`judging.py` + `tools/judge_selftest.py`** (247 LOC, 20 calibration fixtures) — TG4 extends
  the fixtures with an inter-ensemble agreement metric.
- **`tools/{rag_poison,memory_poison,agentharm,indirect_inject}.py`** — existing thin
  implementations + the AgentDojo/injection-bank scaffolding referenced in `IMPROVEMENT_ROADMAP.md`
  Phase 5. H fills these out rather than adding new tool files.
- **`tools/leaderboard.py`** — I adds a `--cross-family` mode here.
- **`_fsutil.atomic_write`** — reused for bandit-posterior and cross-family state persistence.
- **`providers/factory.py` `provider_scope()`** — G's concurrent arm fires and J's workers must
  still close pooled clients at the tool-call boundary through this chokepoint.
- **`tools/registry.py` `ToolContext`** — item B decomposes this; the delegating-property approach
  keeps all ~80 tool call sites and `ctx.emit/run/record_verdict` working unchanged.

## 6. PBT Tooling Decision (mandated note)

- **Stack:** Python 3.11+ (all capability code). Framework: **Hypothesis**.
- **Emphasis shift vs. the hardening spec:** that spec's properties were access-control / SSRF /
  session. This is capability work, so the mandated 5 categories map primarily to **Data
  Integrity / Correctness** (embedding-migration round-trips, bandit-posterior persistence,
  transfer-score conservation) and **Input Validation** (family-classifier totality, agentharm
  argument grading). **Rate/Concurrency** re-engages only for J (token-bucket, worker pool).
  **Access Control / Session** are inherited from the hardening spec and re-touched only by J's
  distributed worker (an authorized-target guard). This is called out so no property is written as
  theater against a category the code doesn't exercise.
- **Property file:** `pbt-properties.py` (Hypothesis). Any UI-only invariants: none in this spec.

## 7. Constraints & Non-Functional Requirements

- **No-config default must not regress.** Item A ships with `strategy_embeddings = "bm25"` as the
  zero-dep, zero-latency, zero-cost fallback; `"openai"`/`"local"` are opt-in. A fresh checkout
  with no API key behaves at least as well as today's BoW.
- **Backward-compatible library.** Old JSONL rows without `embedding_model` must still load; they
  are lazily re-embedded under the active backend on first retrieve, never dropped.
- **Refactor safety (B).** ToolContext decomposition is phase-1 delegation only — **zero tool
  signature changes**; the full existing test suite must pass unchanged.
- **Cost containment.** Any embedding-API or ensemble-judge call is opt-in and bounded; default
  paths make no extra network calls.
- **Dual-use discipline.** Agentic surfaces (H) and multimodal remain gated behind the existing
  "authorized testing only" doctrine; no change to the responsible-use posture.
- **Estimation in iterations, never hours/days.**

## 8. Open Questions (non-blocking; defaults assumed)

1. **Embedding backend for the recommended default (A).** Assume `bm25` no-config fallback +
   `openai:text-embedding-3-small` as the recommended opt-in, `local` = an ONNX
   sentence-transformer. Revisit `local` model choice if offline operation is a hard requirement.
2. **Family taxonomy granularity (D).** Assume 5 families: `openai`, `anthropic`, `google`,
   `deepseek`, `meta/llama`, + `other`. Sub-family (e.g. reasoning vs. chat) deferred to I.
3. **Distributed backend (J).** Assume SQLite-backed queue + pluggable strategy store
   (JSONL→SQLite→Postgres) as the single-team default; Redis/pgvector only when >10k library
   entries or multi-machine. J is gated on demonstrated single-machine ceiling, not built
   speculatively.
