# Wallbreaker 全量审计报告

| 字段 | 值 |
|------|-----|
| **日期** | 2026-07-26 |
| **范围** | 核心包 `wallbreaker/` · Dashboard · Desktop · 配置/运行态 · 测试套件 |
| **方法** | 静态代码审计 + 配置/运行日志取证 + 全量 pytest（忽略可选依赖）+ 安全边界与并发路径专项 |
| **标准** | 顶格：安全 > 正确性 > 可观测性 > 可维护性 > 体验 |
| **结论等级** | **有条件可用（Conditional Go）** — 本地授权红队可用；**不可**按多租户/公网服务部署 |

---

## 0. 执行摘要

### 总评

| 维度 | 评级 | 说明 |
|------|------|------|
| 安全（本地单用户） | **C+** | 默认绑 127.0.0.1、CORS 收紧；但 agent 具备**无沙箱 shell + 任意 HTTP**，Dashboard **无鉴权** |
| 正确性 / 可靠性 | **C** | BUG-001 部分修复；**大量工具仍用 `asyncio.wait_for` 中途掐流** |
| 配置与密钥 | **B-** | Key 进 `.env` 设计合理；明文 `api_key` 仍可写 toml；DeepSeek 无效 Key 会静默拖垮目标 |
| 测试健康 | **D+** | **1071 passed**；**37 failed + 7 errors**（缺 library 语料 / PIL） |
| 桌面端 | **B** | 生命周期/保活/模型池可用；`sandbox:false`、路径 IPC 过宽 |
| 产品完成度 | **B-** | TUI+Dashboard+Desktop 齐；模型池/中文 UI/页签保活已补 |

### 一句话

> **这是一台给授权操作者的“重火力红队机床”**，不是安全的通用 SaaS。本地自用可继续测；在修完 **wait_for 掐流族**、**SSRF/shell 边界**、**测试/语料依赖** 前，不要扩大暴露面。

---

## 1. 审计范围与方法

### 覆盖

1. **Provider 层**：OpenAI / Anthropic / Image / RequestGate / complete 流式  
2. **Tools 层**：`query_target`、`profile_target`、并发 sweep、`run_shell`、`http_request`、files  
3. **Dashboard API**：providers / probe / model-pool / agent SSE / runs / CORS  
4. **Desktop shell**：Electron 安全、后端托管、IPC  
5. **配置运行态**：`config.toml`、`.env` 模式、最新 `sessions/run-*.jsonl`  
6. **测试**：全量 pytest（ignore 可选 PIL 收集失败模块时仍见 37 fail）

### 证据源

- 代码：`wallbreaker/**/*.py`、`desktop/src/**`、`dashboard/web/src/**`  
- 运行：`sessions/run-20260726-061510.jsonl`（CancelledError 实锤）  
- 测试：`pytest -q --ignore=tests/test_typographic.py` → 1071 pass / 37 fail / 7 error  

---

## 2. 严重发现（按优先级）

### P0 — 致命 / 部署禁令

#### P0-1 · Agent 任意 Shell（`run_shell`）

| | |
|--|--|
| **位置** | `wallbreaker/tools/shell.py` |
| **问题** | `asyncio.create_subprocess_shell(command)`，**无命令白名单、无网络隔离、无容器沙箱** |
| **影响** | 攻击者大脑一旦被诱导（prompt injection / 越狱成功后的 tool 调用），可在本机执行任意命令 |
| **场景** | 设计如此（红队 harness 要“能干活”），但对 **Dashboard 远程可达** 或 **不可信 attacker 模型** 极危险 |
| **建议** | ① 默认关闭 `run_shell`（配置开关）② allowlist / 工作区 chroot ③ 高危工具需 operator 确认 ④ 永不把 dashboard 绑 `0.0.0.0` 且无认证 |

#### P0-2 · 任意 HTTP / SSRF（`http_request`）

| | |
|--|--|
| **位置** | `wallbreaker/tools/http_tool.py` |
| **问题** | 任意 URL + method + headers + body，`follow_redirects=True`，无内网/metadata 阻断 |
| **影响** | 可打 `169.254.169.254`、内网管理口、localhost 其他服务；可当跳板 |
| **建议** | blocklist：link-local、RFC1918（可配置）、file://；可选 allowlist host；禁 redirect 到内网 |

#### P0-3 · Dashboard 无鉴权

| | |
|--|--|
| **位置** | `dashboard/server.py` `serve(host=127.0.0.1)` |
| **问题** | 所有 `/api/*`（含 fire、agent/run、providers、写入 `.env`）**无 token/登录** |
| **缓解** | 默认 localhost + CORS 仅 localhost（好） |
| **风险** | 本机恶意网页/扩展若能打 127.0.0.1:8787 → 间接控 agent；绑定公网则全盘沦陷 |
| **建议** | 可选 `DASHBOARD_TOKEN`；拒绝非 loopback 默认；公网必须反向代理 + mTLS/BasicAuth |

#### P0-4 · `POST /api/providers/probe` 可被滥用为 SSRF + 密钥探测

| | |
|--|--|
| **位置** | `dashboard/server.py` `provider_probe` |
| **问题** | 客户端提交 `base_url` + `api_key`，服务端代发 HTTP GET `/models` |
| **影响** | 与 P0-2 同类；且可把用户粘贴的 key 打到恶意 URL |
| **建议** | URL allow scheme http(s)；禁私网；记录审计日志；rate limit |

---

### P1 — 高：正确性 / 可靠性（直接影响你“跑一半 network error”）

#### P1-1 · `asyncio.wait_for` 掐流族（BUG-001 扩散）

| | |
|--|--|
| **已修** | `profile_target` 去掉 target 上的 `wait_for`；`complete_with_reasoning` 支持 partial |
| **未修** | 代码库仍有 **约 65 处** `asyncio.wait_for`：`framing_sweep`、`multi_fire`、`best_of_n`、`campaign`、`crescendo`、`pair`、`evolve_persona`、`drattack`… |
| **机制** | wait_for 超时 → **CancelledError** 取消协程 → 流式半截 → 旧逻辑标 ERROR/network |
| **实锤** | `run-20260726-061510.jsonl`：`text_delta` 已有完整拒答仍 `CancelledError` + `ERROR` |
| **建议** | 统一策略：**禁止**对 streaming complete 套短 wait_for；只用 httpx timeout；或 wait_for 超时后 **回收 partial**（base 已支持） |

#### P1-2 · 错误标签过宽（残留）

| 文件 | 状态 |
|------|------|
| `openai_provider.py` | **已改**：有内容则 soft partial；无内容区分 timeout/connect/http |
| `anthropic_provider.py` | **仍** `network error from {url}` 一把梭 |
| `image_provider.py` | **仍** 同上 |
| 多工具 `except Exception → ERROR` | 丢失真实异常类型 |

#### P1-3 · 并发门闩 vs 工具自建并发

| | |
|--|--|
| **RequestGate** | 默认 concurrency=3 + delay 250ms（按 credential） |
| **工具** | `profile_target`/`framing_sweep`/`multi_fire` 再 `gather_capped` |
| **结果** | 总并发被 gate 限住会排队；短 wait_for 更容易误超时 → 假 ERROR |
| **建议** | 工具 timeout 必须 **≥ 单请求 HTTP timeout × 重试**；文档写明 gate 与工具 concurrency 关系 |

#### P1-4 · 配置 timeout=0 语义

| | |
|--|--|
| **现象** | `config.toml` / 运行日志里 target `timeout: 0.0` |
| **实际** | `build_provider`：`endpoint.timeout or DEFAULT_TIMEOUT(120)` → **仍 120s** |
| **问题** | 日志/UI 显示 0 误导排障；与工具级 45s wait_for 叠加时更混乱 |
| **建议** | 序列化时写 resolved timeout；UI 显示有效超时 |

---

### P2 — 中：安全加固 / 产品一致性

#### P2-1 · 文件写入逃逸（部分缓解）

- `_confine` 会把 **cwd 外绝对路径** 重定向回工作区  
- **相对路径写 `.env` / `config.toml` 仍允许**（agent 可改密钥配置）  
- **建议**：敏感文件 deny-list；写操作审计

#### P2-2 · Electron

| 项 | 现状 | 风险 |
|----|------|------|
| `contextIsolation` | true | 好 |
| `nodeIntegration` | false | 好 |
| `sandbox` | **false** | 中 |
| `openPath` | **任意路径** | 中（预加载暴露 IPC） |
| 后端 | 子进程托管 | 好 |
| 单实例 | 有 | 好 |

**建议**：`sandbox: true`；`openPath` 限制在 `WALLBREAKER_ROOT` 与 userData。

#### P2-3 · 密钥落盘

- 优先 `api_key_env` + `.env`：**正确**  
- 仍支持 toml 内联 `api_key`：易进 git  
- `has_api_key` 不回传明文：**正确**  
- **建议**：保存时拒绝 toml 明文 key；`.gitignore` 已含 `.env`/`config.toml`（确认用户未强制 add）

#### P2-4 · 测试 / 语料依赖

失败簇（样本）：

- `library/` 下 **ENI / jailbreaks / system prompt 语料** 缺失 → eni/persona/sysprompt 测试挂  
- **PIL** 缺失 → typographic/session_card  
- 与核心 provider 逻辑无关，但 **CI 绿灯假象不足**

**建议**：`pytest` 分 marker：`core` / `library` / `optional`；README 写清 `library` 拉取步骤。

#### P2-5 · Anthropic/Image 未享受 BUG-001 修复

与 OpenAI 路径行为不一致 → 多协议目标时错误形态分裂。

---

### P3 — 低：工程质量

| ID | 项 | 说明 |
|----|----|------|
| P3-1 | 宽 `except Exception` | 全库大量吞异常，排障靠猜 |
| P3-2 | 双 Node 安装 | `Program Files` + `pi-node` 并存，脚本依赖 PATH 顺序 |
| P3-3 | Dashboard 前端英文残留 | 部分 ProviderManager 文案未汉化 |
| P3-4 | Starlette TestClient deprecation | 依赖升级噪音 |
| P3-5 | 模型池与 Profiles 双轨 | 顶栏走池，Profiles 页仍复杂，心智负担 |

---

## 3. 专项：你反馈的 “network error”

### 3.1 已证实机制（日志）

```
profile_target step → asyncio.wait_for(45s) 
  → 模型仍在 stream（已有 text_delta 数百）
  → CancelledError
  → 工具记 ERROR
  → 旧文案/习惯称为 network error
```

### 3.2 已落地修复

1. `complete_with_reasoning`：取消/传输错误时 **尽量返回 partial 文本**  
2. OpenAI stream：有内容则 soft `partial`，无内容细分 timeout/connect/http  
3. `profile_target`：去掉 target `wait_for`，默认 120s  
4. `query_target` 错误 hint 分类  
5. 测试更新并通过（provider timeout 相关）

### 3.3 仍会“像 network”的路径

1. **未改的 wait_for 工具**（framing_sweep / multi_fire / …）  
2. **CPA 真断连 / 进程挂**  
3. **DeepSeek 401**（已是 auth，但旧会话配置可能仍指向无效 key）  
4. **前端 Failed to fetch**（后端重启中）— 已有中文提示  

### 3.4 操作者判定口诀

| 信号 | 含义 |
|------|------|
| run log 有完整 `text` + `CancelledError` | **超时掐流**，不是网线 |
| `HTTP 401` / authentication | **Key** |
| `connect error` | **真连不上** |
| Findings 有 COMPLIED 但最后一行 ERROR | **混合结果**，以 findings 为准 |
| 仅 `Failed to fetch` | **Dashboard 进程** |

---

## 4. 安全模型（威胁建模摘要）

```
[不可信] Attacker LLM 输出 tool_calls
    ↓
[高权限] Tool registry (shell, http, files, fire)
    ↓
[本机] 文件系统 / 内网 / 外网 API
    ↓
[敏感] .env keys, sessions 有害内容, config
```

**信任边界断裂点**：Attacker 模型 ⇄ 工具层 **无二次确认**。  
对授权红队可接受；对共享机器/多用户 **不可接受**。

---

## 5. 测试与质量门禁

| 指标 | 结果 |
|------|------|
| 通过 | **1071** |
| 失败 | **37** |
| 收集错误 | **7**（persona_spec 等 FileNotFound） |
| 跳过 | 9 |
| 核心 provider/timeout | 近期相关用例 **通过** |

**门禁建议**

```text
P0 gate (每次 PR):  pytest -m core   # 需新增 marker
P1 nightly:        full + library present
可选:              barcodes/PIL extras
```

---

## 6. 配置运行态快照（审计时）

| 项 | 值 |
|----|-----|
| default_profile | `cpa` |
| target | `grok-4.5` @ `http://127.0.0.1:8317/v1` |
| target.timeout 字段 | `0.0`（实际 fallback 120s） |
| profiles | xai, deepseek, cpa |
| Dashboard | 8787 LISTEN |
| CPA | 8317 LISTEN |
| library 目录 | 有 L1B3RT4S 等；**ENI/部分语料测试仍缺文件** |

---

## 7. 优先修复路线图（顶格顺序）

### 本周必须（P0/P1）

| # | 行动 | 验收 |
|---|------|------|
| 1 | **全库去掉对 streaming complete 的短 wait_for**（或超时回收 partial） | 再无 “有 text 却 ERROR” 的 run log |
| 2 | Anthropic/Image 对齐 OpenAI 错误分类 | 无裸 `network error` 一把梭 |
| 3 | `run_shell` / `http_request` 配置级 disable + SSRF 护栏 | 默认安全档可关高危工具 |
| 4 | Dashboard 可选 token；禁止非 loopback 无认证 | 文档 + 代码双保险 |
| 5 | pytest `core` marker，CI 只挡核心 | 1071 绿里抽出稳定子集 |

### 两周内（P2）

| # | 行动 |
|---|------|
| 6 | 敏感路径写保护（.env/config.toml） |
| 7 | Electron sandbox + openPath 白名单 |
| 8 | 库语料安装脚本 / 子模块说明 |
| 9 | 有效 timeout 显示与配置归一 |
| 10 | 多步工具汇总 UI：successes/errors 分列 |

### 不做也声明

- 不把本工具当多租户平台  
- 不默认公网暴露 dashboard  
- 不在未隔离环境对不可信 attacker 模型开放 shell  

---

## 8. 评分卡（百分制粗评）

| 类别 | 分 | 权重 | 加权 |
|------|----|------|------|
| 安全边界 | 55 | 25% | 13.8 |
| 运行正确性 | 62 | 25% | 15.5 |
| 可观测/排障 | 70 | 15% | 10.5 |
| 测试可信度 | 58 | 15% | 8.7 |
| 产品体验 | 75 | 10% | 7.5 |
| 工程可维护 | 68 | 10% | 6.8 |
| **总分** | | | **≈ 62.8 / 100** |

**解读**：达到“强力本地红队原型”水准；距“可交付加固产品”差在 **工具沙箱、超时语义统一、测试/语料完整性**。

---

## 9. 立即行动清单（给你现在用）

1. **继续只用 127.0.0.1**；不要改 host 为 0.0.0.0。  
2. **重启后端**以加载 BUG-001 部分修复。  
3. 排障时 **先看 `sessions/run-*.jsonl`**，不要只看最后一行 network。  
4. 目标优先 **CPA 可用模型**；DeepSeek 在 Key 修复前勿切回。  
5. 需要稳定画像时：对 `profile_target` 显式大 timeout（现默认 120）。  
6. 接受：全量 pytest 因缺 library/PIL **现在不是全绿**，不代表核心全挂。

---

## 10. 附录：关键文件索引

| 风险点 | 文件 |
|--------|------|
| Shell | `wallbreaker/tools/shell.py` |
| SSRF HTTP | `wallbreaker/tools/http_tool.py` |
| 流式 partial | `wallbreaker/providers/base.py` |
| OpenAI 错误 | `wallbreaker/providers/openai_provider.py` |
| 仍 network 一把梭 | `anthropic_provider.py`, `image_provider.py` |
| wait_for 扩散 | `tools/framing_sweep.py`, `multi_fire.py`, `best_of_n.py`, … |
| Dashboard CORS/API | `dashboard/server.py` |
| 密钥 | `provider_registry.py`, `config.py` |
| Desktop | `desktop/src/main.ts` |
| 已知缺陷 | `docs/BUGS.md` |
| 本报告 | `docs/FULL_AUDIT_2026-07-26.md` |

---

*审计完成。未在本轮扩大改代码范围；P1-1 全库 wait_for 收敛建议作为下一专项 PR。*
