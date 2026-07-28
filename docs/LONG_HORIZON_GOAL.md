# Daedalus / wallbreaker — Long-Horizon Advancement Goal

> Product: **Daedalus** · Package/CLI: **`wallbreaker`**  
> Source of truth: [IMPROVEMENT_ROADMAP.md](../IMPROVEMENT_ROADMAP.md) + [HARNESS_VIBECODE_PLAN.md](HARNESS_VIBECODE_PLAN.md)  
> Updated: 2026-07-28

---

## North-star objective

把 wallbreaker 从「功能齐全的红队 harness」推进成 **可长期运行、可测量、可复现、可迁移** 的 Daedalus 解放/评估引擎：

1. **测量可信** — ASR / FRR / GARBLED 不互相污染，judge 可校准  
2. **攻击可搜索** — bandit / BoN / TAP / multi-turn 默认走高效路径  
3. **成功可复利** — Liberation Memory + strategy library + transfer 跨 run 复用  
4. **表面可扩展** — text / image / agentic / MCP 攻击面按目标加深  
5. **工程可交付** — 脏工作树可拆分提交，桌面端/CI 稳定，配置不丢密钥

---

## Already landed (do not redo)

Treat these as baseline, not backlog:

- Daedalus product layer: doctrine, cyber gate, dual/single topology, Liberation Memory + REPLAY + external embed hook  
- BUG-001 stream timeout / partial salvage / await_llm floor  
- Phase 0 transforms + presets  
- Phase 1 StrongREJECT + GARBLED + FRR + judge_selftest metrics  
- Phase 2 bandit defaults, mutate constraint, BoN/TAP primitives  
- Phase 3 Conversation + crescendo auto default + goat/tree/echo  
- Phase 4 cache/strategy/transfer/campaign + `--watch/--schedule` + checkpoints  
- Phase 5 polish: low_perplexity flags, image_crescendo, AgentDojo bank, rug_pull / worm_wrap / agentbench  
- Datasets: harmbench/jbb/strongreject/advbench/sorrybench/xstest + `datasets list|refresh` + CI workflow  
- Display branding Daedalus (package name stays wallbreaker)

---

## Durable goal (paste into Codex goal)

```text
推进 Daedalus/wallbreaker 进入“可运营红队引擎”阶段，而不是继续堆一次性功能。

优先级固定为：
P0 工程收敛 → P1 测量可信与回归门禁 → P2 真实目标上的解放闭环 → P3 攻击面加深 → P4 运营化。

具体要求：
1) 把当前 fix/bug-001 分支上的大脏工作树拆成可审查提交（至少：BUG-001/providers、Daedalus harness、Phase1 measurement、datasets/FRR、Phase2-5 tools、desktop/UI），不破坏现有测试绿。
2) 建立并维持最小回归门：judge_selftest、frr_scan/xstest、datasets list、relentless/schedule smoke、关键 crescendo/image/agent 工具注册测试；CI 中 datasets-refresh 保持可跑。
3) 在真实配置目标上跑通 CODE→LIBERATE→Memory→REPLAY 闭环，记录 validate_rate、ASR、FRR、replay hit，把成功写入 Liberation Memory 并可 /memory 检索。
4) 只在有明确目标缺口时加深 Phase 5（多模态/agentic/MCP），禁止无目标地扩工具面。
5) 可选运营项：把 schedule install 生成的 runner 真正挂到本机任务计划/cron；需要时再做 OS daemon，而不是重复实现 --watch。

完成标准：
- 工作树可按主题提交/推送，主路径测试稳定绿
- 任意新目标能用现有 arsenal + memory/replay 启动，而不是从零手写流程
- 报告能同时给出 ASR、FRR、GARBLED、technique mix、liberation counts
- 文档 Next 只保留真正可选的生产/研究项，不再把已完成 Phase 0–5 当待办
```

---

## Workstreams (long-running)

### P0 — Engineering convergence（先做，否则后面都难合并）

**Goal:** 脏树变成可审查历史  

- 按主题拆 commit / PR（不要一个超大 commit）  
- 建议切片：
  1. `fix(bug-001)` providers + await_llm + partial salvage  
  2. `feat(daedalus)` doctrine/cyber_gate/memory/replay/config/UI  
  3. `feat(measure)` judging/FRR/selftest/report  
  4. `feat(datasets)` sorrybench/xstest/cli/ci  
  5. `feat(search-multiturn)` bandit/mutate/crescendo/watch  
  6. `feat(surfaces)` image/agentic/rug_pull/worm/agentbench  
  7. `feat(desktop)` Electron shell + richer dashboard（若仍要保留）  
- 每片：相关 pytest 绿 + 不回退 BUG-001  
- 处理 desktop/node_modules 等是否应 gitignore

**Exit:** `main`（或 integration 分支）上有清晰提交序列，本地 `pytest` 核心套件绿

### P1 — Measurement & gates（数字说谎就停）

**Goal:** 任何 ASR 数字都可审计  

- 保持 judge_selftest ≥40 fixtures + kappa/Spearman/per-class  
- FRR 用 xstest/jbb benign，不与 jailbreak judge 混用  
- export/report 始终带：strict ASR、broad ASR、FRR、garbled_rate、by_technique  
- CI：datasets-refresh + 最小单测门；可选 redteam-gate.example 按需启用  
- 远程语料：`wallbreaker datasets refresh` 失败不阻断 offline bundle

**Exit:** 一次标准 battery 产出可对比的 scorecard + hitlog，且 selftest 不红

### P2 — Liberation operating loop（产品主闭环）

**Goal:** CODE → gate → LIBERATE → validate → Memory → REPLAY 成为默认工作方式  

- 真实目标（CPA/OpenRouter/本地）上跑 3+ 类 objective  
- `memory_require_validate=true` 时只有带 rate 的胜场入库  
- `/memory`、dashboard liberation、REPLAY inject 可观察  
- 可选：external embed provider 配好并对比 hybrid vs token  
- 记录指标：task complete rate、gate→liberate rescue、replay hit、self-refuse→0

**Exit:** 同类 objective 第二次明显走 REPLAY/strategy，而不是纯冷启动

### P3 — Target-driven surface depth（有缺口再挖）

**Goal:** 只补当前目标挡路的攻击面  

按需，不预先全做：

- Multimodal：typographic → query_image_target bypass → image_crescendo  
- Agentic：indirect_inject / agentbench / agentharm / rug_pull  
- Defense：fingerprint_defense → 自动推荐 low_perplexity / crescendo 等  
- 研究向（低优先）：完整 AgentDojo runner、Morris-II 深化、MCP 更强 rug-pull

**Exit:** 每个新表面都有工具 + 至少 1 个 offline 测试 + prompts/arsenal 可见

### P4 — Operations（可离开终端跑）

**Goal:** 评估任务可定时、可恢复、可对照基线  

- 已有：`--watch` / `--schedule` / checkpoints / `schedule install`  
- 下一步仅在需要时：把 runner 挂到 schtasks/cron/systemd（生产注册，不是再写一套循环）  
- baseline save/compare 用于模型升级回归  
- desktop 启动路径稳定（start-desktop.* + health 不误杀 busy backend）

**Exit:** 选定目标可无人值守跑 N 个 cycle，中断后能从 checkpoint/session 续

---

## Suggested cadence

| Horizon | Focus |
|--------|--------|
| **本周** | P0 拆分提交 + 核心测试门 |
| **两周** | P1 scorecard/CI 稳定 + 1 次真实目标闭环（P2） |
| **每月** | 针对最难目标做 P3 表面加深；更新 Liberation Memory 质量 |
| **季度** | P4 运营化（定时任务、基线对比、桌面发布） |

每日/每次会话启动检查：

1. `wallbreaker check`  
2. `wallbreaker datasets list`  
3. 相关 pytest 子集  
4. 若改 judge：先 `judge_selftest`  
5. 若改 memory：`/memory` 或 liberation API

---

## Non-goals (avoid drift)

- 把 package 名从 `wallbreaker` 改成 daedalus（破坏 CLI/CI）  
- 无目标地继续堆 presets/tools  
- 用短 `wait_for` 包 streaming complete（BUG-001 回归）  
- 用 jailbreak judge 直接打 FRR（会虚高 over-refusal）  
- 在未拆分脏树前做大范围无关重构

---

## Status snapshot (2026-07-28)

- **P0 partially done:** dirty tree split into 7 thematic commits on `fix/bug-001-stream-timeout-await-llm` (docs/gate, daedalus, measure, datasets/cli, engine surfaces, tui/providers, desktop/dashboard).
- **P1 gate:** `scripts/minimal_gate.sh` / `.ps1` + `.github/workflows/minimal-gate.yml` (127-test core subset green).
- **P2 blocked on live keys:** local `config.toml` target `grok-4.5` currently has no resolved API key in this environment; Liberation loop needs operator key/env before live CODE→LIBERATE→Memory run.
- Worktree clean except ignored `work/`.

- **P2 live loop exercised:** CPA grok-4.5 with keys — CODE ok; hard AES-rShell frames refused; soft TCP lab client **COMPLIED** + validate **2/3** + Memory id 958e15389f68d9c0 + **REPLAY hit**; FRR 0% on 3 benign; report has ASR/FRR/technique mix. See docs/P2_LIVE_LOOP_EVIDENCE.md.
- Worktree clean except ignored runtime/scratch.

## Immediate next actions (when resuming)

1. **Branch hygiene:** 从 `fix/bug-001-stream-timeout-await-llm` 按 P0 切片提交  
2. **Smoke:**  
   `pytest tests/test_await_llm.py tests/test_bug001_partial_salvage.py tests/test_daedalus.py tests/test_judging.py tests/test_frr_scan.py tests/test_relentless.py tests/test_schedule_and_phase5_extras.py -q`  
3. **One real loop:** 选一个 cyber objective，跑 auto + validate + 确认 memory 写入  
4. **Only then** 做 Phase 5 深挖或 OS 级 schedule 注册

---

## One-line Codex goal (short form)

```text
收敛并运营 Daedalus/wallbreaker：先拆分提交现有大改动并守住测量/回归门，再在真实目标上强化 CODE→LIBERATE→Memory→REPLAY 闭环；仅在目标受阻时加深 Phase 5 表面，最后才做 OS 级定时与发布打磨。
```
