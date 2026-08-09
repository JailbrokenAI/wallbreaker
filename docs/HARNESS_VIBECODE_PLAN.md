# Daedalus — Vibecoding Harness + Liberation Plan

**Codename:** Daedalus (代达罗斯) — temporary product name drawn from myth: the
craftsman who maps the labyrinth and builds the exit. UI copy can change later;
keep the codename in config as `daedalus.codename`.

**Repo product:** Wallbreaker runtime under the Daedalus product layer.

## Decisions locked (2026-07-28)

| # | Decision | Value |
|---|----------|--------|
| 1 | Model topology | **Both dual and single**, operator-configurable in Settings / `[daedalus].topology` |
| 2 | Liberation memory | **Global** (`library/liberation/`) |
| 3 | Default UI copy | Keep Wallbreaker for now; codename Daedalus for product layer; rename later |
| 4 | Doctrine | Written to `wallbreaker/doctrine/liberation_agent.md` and injected via `compose_system` |

## Product loop

```
CODE (vibecoding / RE) 
  → cyber gate trip 
  → LIBERATE (existing attack arsenal) 
  → success 
  → GLOBAL Liberation Memory 
  → next similar request REPLAY first
```

### Topology

- **`dual`** (default): attacker brain and target may differ (`[agents.attacker]` vs
  `[agents.target]` / `[target]`). Liberation campaigns hit the target model.
- **`single`**: target mirrors the attacker endpoint after config load. One model
  codes and is also the liberation surface.

Toggle in `config.toml`:

```toml
[daedalus]
codename = "Daedalus"
topology = "dual"   # or "single"
doctrine_enabled = true
doctrine_file = "wallbreaker/doctrine/liberation_agent.md"
memory_scope = "global"
memory_root = "library/liberation"
cyber_gate_enabled = true
```

Env overrides:

- `WALLBREAKER_DOCTRINE=0` — disable doctrine inject
- `WALLBREAKER_DOCTRINE_FILE=/path/to.md` — custom doctrine path
- `WALLBREAKER_TOPOLOGY=single|dual` — override topology

## Modules

| Path | Role |
|------|------|
| `wallbreaker/doctrine/liberation_agent.md` | Brain liberation constitution |
| `wallbreaker/doctrine/__init__.py` | Load / enable helpers |
| `wallbreaker/memory/liberation_store.py` | Global save / find_similar / replay_block |
| `wallbreaker/prompts.compose_system` | Injects doctrine when enabled |
| `config [daedalus]` | Topology + memory + doctrine flags |

## Phased work

### Done

- [x] Codename Daedalus
- [x] Doctrine file
- [x] Plan doc
- [x] Config section + dual/single apply
- [x] Global LiberationStore
- [x] compose_system doctrine inject
- [x] Cyber gate in `agent/loop.py` (prose refusal → MODE LIBERATE nudge, max 3)
- [x] Moral finish bounce appends liberate nudge
- [x] Auto Liberation Memory writeback on COMPLIED/PARTIAL (`ToolContext.record_verdict`)
- [x] REPLAY inject at `run_autonomous` start (global similarity)
- [x] Wired CLI / TUI / Dashboard

### Done (this pass)

- [x] Desktop Settings UI for topology + doctrine + cyber_gate + memory_require_validate
- [x] validate-gated memory save (`memory_require_validate`; validate tool writes rate)
- [x] `/liberate` slash command + TUI/Dashboard mode badges (CODE/LIBERATE/REPLAY)
- [x] Hybrid Liberation Memory retrieval — offline hashed embed + token fallback
  (`find_similar(method=hybrid|token|embed)`, `WALLBREAKER_MEMORY_EMBED=0` kills embed;
  optional `embed_fn` hook for external vectors; REPLAY uses hybrid)
- [x] `cosine_similarity` L2-normalizes both sides (non-unit `embed_fn` safe)
- [x] REPLAY reliability boost — `validate_rate` + `hits` rank additives
  (`parse_validate_rate`, `reliability_boost`; cap +0.25)
- [x] Dashboard Settings HTTP round-trip for `[daedalus]` flags
- [x] Effective timeout resolve (`resolve_timeout` / `Endpoint.effective_timeout`;
  config `timeout=0` no longer reported as 0s — audit P1-4)
- [x] Liberation Memory inspect — `store.stats` / `list_recent`,
  `GET /api/liberation`, TUI `/memory [query]`, overview `liberation` counts
- [x] Docstrings: fingerprint/`_echo` no longer claim raw short `wait_for` on streams
  (they use `await_llm` ≥120s floor)

### Next

- [x] P2 live: CPA grok-4.5 loop — soft lab COMPLIED+validate+Memory+REPLAY (hard AES frames refused); see P2_LIVE_LOOP_EVIDENCE.md
- [ ] Optional: register generated schedule runners into real OS task schedulers in production
- [ ] Optional research deepenings beyond the in-tree AgentDojo/Morris-II wrappers

### Done (P2 live loop)

- [x] Real CPA target fire + judge + validate + Liberation Memory + REPLAY
- [x] FRR sample + aggregate ASR/FRR/technique report fields from run logs
- [x] Evidence note docs/P2_LIVE_LOOP_EVIDENCE.md

### Done (P0 engineering convergence)

- [x] Dirty tree split into thematic commits on `fix/bug-001-stream-timeout-await-llm`
- [x] Minimal regression gate scripts + `minimal-gate` workflow
- [x] Offline dataset fixtures under `wallbreaker/datasets/fixtures/`
- [x] Worktree clean (only ignored scratch)

### Done (schedule daemon + Phase 5 extras)

- [x] `wallbreaker schedule install|list|uninstall` + `schedule_daemon.py` (runner + OS hints)
- [x] `rug_pull` tool-schema bait-and-switch
- [x] `worm_wrap` Morris-II self-replication wrapper + worm-ASR
- [x] `agentbench` AgentDojo-style indirect injection battery

### Done (Phase 5 surface polish)

- [x] `Transform.low_perplexity` flag + `low_perplexity_transforms()` / high counterpart
- [x] fingerprint_defense points PPL hits at fluent transform set
- [x] AgentDojo-style indirect inject bank (+ reminder/tool_note/email_fwd); default important_instructions
- [x] `image_crescendo` tool alias; `image_chain` default `mode=auto`
- [x] CLI `--schedule` alias for `--watch`

### Done (relentless watch + datasets CI)

- [x] `wallbreaker/relentless.py` — interval parse, watch loop, checkpoint I/O
- [x] `run_autonomous(on_checkpoint=...)` mid-run session persistence
- [x] CLI `--watch [30s|5m|1h]`, `--watch-max-cycles`, `--checkpoint`
- [x] Active `.github/workflows/datasets-refresh.yml` (+ example kept)

### Done (README + datasets CLI / campaign bandit)

- [x] README product-vs-package table; display name Daedalus, CLI `wallbreaker`
- [x] `wallbreaker datasets list|refresh` + `datasets.status` / `datasets.refresh`
- [x] `.github/workflows/datasets-refresh.example.yml` for weekly corpus refresh
- [x] `campaign` bandit default **on** (aligned with recommend/seed_sweep)

### Done (product rename / Phase 3 defaults)

- [x] User-facing brand **Daedalus** (dashboard wordmark/i18n/title, desktop productName,
  CLI description, TUI repro pack, notify titles)
- [x] `wallbreaker.branding` helpers; respects `[daedalus].codename`
- [x] Package/CLI/import path remain `wallbreaker` (compatibility)
- [x] `crescendo` default `mode=auto` (Crescendomation + auto-backtrack)

### Done (datasets + Phase 2 defaults)

- [x] XSTest-style benign corpus (`library/xstest_benign_prompts.csv`) + `xstest` source
- [x] `recommend_transforms` / `seed_sweep` bandit default **on** (UCB1; cold-start safe)
- [x] `mutate` constraint prune default **on** when `variants>1`

### Done (FRR / over-refusal)

- [x] `datasets` benign filter (`benign=True/False`) + `has_benign`
- [x] `frr_scan` tool (benign battery → FRR / help_rate, benign-tagged verdicts)
- [x] Report scorecard `frr` / `benign_help_rate` from benign-tagged verdicts
- [x] `judge_selftest` expanded to 45 fixtures with FRR section
- [x] `record_verdict(..., benign=True)` / `RunLog.verdict` axis tags

### Done (Phase 1 measurement hardening)

- [x] StrongREJECT fields retained on judge path + `strongreject_score` helper
- [x] `grade()` GARBLED short-circuit before LLM judge (not mislabeled REFUSED)
- [x] `judge_selftest` kappa / Spearman / per-class TPR-FNR-FPR
- [x] Report outcome counts include garbled + refused rates

### Done (external embed pass)

- [x] Optional external embedding provider (OpenAI/OpenRouter/custom) via `memory.embedders`
  (`build_embed_fn` / `OpenAICompatibleEmbedder`, process LRU cache, env overrides)
- [x] Config `[daedalus]` fields + Settings UI + `/api/liberation` embed status
- [x] REPLAY / TUI `/memory` / dashboard similar search pass `embed_fn`
- [x] Audit residual short outer cancels: attack tools use `await_llm` (>=120s floor);
  remaining `wait_for` only on shell/chrome/mcp process bounds + `await_llm` itself

## Keysmith → Daedalus mapping

Keysmith rewrites agent constitution before the session. Daedalus:

1. **Doctrine** = in-process keysmith (always-on brain constitution)
2. **LIBERATE** = wallbreaker arsenal when constitution is not enough
3. **Memory** = compound successful unlocks globally for REPLAY

## Success metrics

- Task complete rate (CODE)
- Gate trip → liberate rescue rate
- Replay hit rate on similar objectives
- Brain self-refuse rate → 0
- Validate≥N before memory save
