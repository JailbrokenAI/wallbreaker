from __future__ import annotations

import dataclasses
import difflib
import re
import shlex
from datetime import datetime

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Input, OptionList, Static
from textual.widgets.option_list import Option


def _strip_surrounding_quotes(s: str) -> str:
    """Remove one layer of matching surrounding quotes.

    Windows path args are pulled from the RAW command text (not the shlex tokens)
    so backslashes survive — but that also keeps the quotes the operator typed
    around a path with spaces. Strip exactly one matching pair so
    ``/session load 'C:\\a b\\run.jsonl'`` loads the real file, while leaving an
    unquoted path (or a path that legitimately ends in a quote) untouched.
    """
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


class PromptInput(Input):
    """Single-line Input that also accepts multi-line pastes and manual soft-newlines.

    Textual's Input keeps only the first line of a paste (``event.text.splitlines()[0]``),
    so a pasted multi-line prompt silently loses everything after line 1. This subclass
    buffers the completed lines of a multi-line paste (and of manual ctrl+j newlines) so the
    whole block submits as one message; the visible field always edits the trailing line.
    Stays an ``Input`` subclass, so ``query_one('#prompt', Input)`` and ``.value`` keep working.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.buffer: list[str] = []

    def _refresh_preview(self) -> None:
        """Mirror the buffered (non-editable) lines into the visible compose preview."""
        try:
            preview = self.app.query_one("#compose-preview", Static)
        except Exception:
            return
        if self.buffer:
            n = len(self.buffer) + 1
            preview.border_title = f"编辑中 · {n} 行"
            preview.remove_class("hidden")
            preview.update("\n".join(self.buffer))
        else:
            preview.add_class("hidden")
            preview.update("")

    def _on_paste(self, event: events.Paste) -> None:
        # Textual dispatches _on_paste to EVERY class in the MRO, so without this the base
        # Input._on_paste would also fire and insert the text a second time. prevent_default()
        # sets _no_default_action, which breaks that MRO loop before the base handler runs.
        event.prevent_default()
        event.stop()
        text = event.text or ""
        if not text:
            return
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        sel = self.selection
        if "\n" not in normalized:
            if sel.is_empty:
                self.insert_text_at_cursor(normalized)
            else:
                self.replace(normalized, *sel)
            return
        lines = normalized.split("\n")
        first, middle, last = lines[0], lines[1:-1], lines[-1]
        if sel.is_empty:
            self.insert_text_at_cursor(first)
        else:
            self.replace(first, *sel)
        self.buffer.append(self.value)
        self.buffer.extend(middle)
        self.value = last
        self.cursor_position = len(last)
        self._sync_subtitle()
        self._refresh_preview()

    def soft_newline(self) -> None:
        """Commit the current line to the buffer and start a fresh editable line."""
        self.buffer.append(self.value)
        self.value = ""
        self.cursor_position = 0
        self._sync_subtitle()
        self._refresh_preview()

    def full_text(self) -> str:
        """The whole composed message: buffered lines joined with the editable line."""
        if self.buffer:
            return "\n".join([*self.buffer, self.value])
        return self.value

    def reset_buffer(self) -> None:
        self.buffer = []
        self.value = ""
        self._sync_subtitle()
        self._refresh_preview()

    def _sync_subtitle(self) -> None:
        n = len(self.buffer)
        self.border_subtitle = (
            f"+{n} 行 · Enter 发送" if n else ""
        )

from ..agent.loop import AgentEvents, run_autonomous, run_turn
from ..agent.messages import TextBlock, ToolResultBlock, user
from ..classify import classify, verdict_color
from ..config import Config, Endpoint
from ..prompts import compose_system
from ..providers.factory import build_provider
from ..session import RunLog
from ..tools import build_registry
from ..transforms import list_transforms
from . import widgets
from .header import StatusHeader
from .sidebar import StatsPanel
from .theme import PALETTE, WB_THEME

HELP_TEXT = """☠ 命令速查 // 斜杠命令说明（命令名保持英文） ☠
/help [topic]         显示帮助；带关键词时只显示匹配行
/edit [new text]      回退到上一条用户消息；预填编辑，或传入新文本后重发
/retry                重新生成对上一条消息的回复
/undo                 删除上一条用户消息及其回复
/profile [name]       查看或切换当前 attacker 配置档
/target [name|model-id]   选择攻击目标（配置档名，或直接模型 id）
/provider [name|none]     固定 OpenRouter 后端，便于结果可复现
/validate [task]          对上次发射或指定任务连打 8 次，估真实成功率
/liberate [note]          手动切入 MODE LIBERATE（注入破限 nudge，或仅切换徽章）
/memory [query]           查看全局 Liberation Memory（统计 / 相似检索）
/replay [n]               把日志里第 N 条（或最后一条）载荷对当前目标重打并重判
/model <id>           覆盖当前 attacker 模型 id
/auto [on|off]        开关自动循环（持续攻击直到完成）
/autoexit [on|off]    代理调用 finish() 后是否退出工具（默认 on）
/rounds <n>           设置自动模式最大轮数
/transforms [filter]  列出 Parseltongue 变换（可选子串过滤）
/encode <chain> <text>    预览变换链结果（不发射），并复制
/diff <a> ;; <b>          对目标发射两份载荷并对比裁决（A/B）
/tools [filter]        列出代理可用工具（可选子串过滤）
/preset [list|name]   精选越狱种子模板（复制到剪贴板）
/objective [text]     设置本次任务目标（写入运行与报告）
/template set <text>  暂存含 {request} 占位符的工作模板，便于手工迭代
/template fire <cat>  用 <cat> 填充 {request} 后发射并自动裁决（另有 set/save/clear）
/template test [a;b]  用类别电池跑模板，输出记分板
/sysprompt set <text> 固定一条 system prompt（或 /sysprompt load <file|seed> 加载人设）
/sysprompt test [prefill] [samples=N]   用 HarmBench 电池扫当前 sysprompt
/lib [list|update|MODEL]   浏览 L1B3RT4S 库
/parsel [list|search q|inspect K|guide|transform K txt|chain k,k txt|decode txt|craft k,k req]   P4RS3LT0NGV3 引擎（222 变换）
/eni [list|search q|MODEL] 浏览 ENI 人设越狱合集
/seedsweep <request>       用多条 ENI+L1B3RT4S 种子打同一请求并排名
/pairsweep [category] [n]   对整组电池并发跑 PAIR（高 ASR 循环）
/narrate <request>         扫 5 种小说章节框架 + prefill，保留成功绕过
/fire <prompt>             手动向目标发射一条提示，裁决并开线程
/push <follow-up>          在该线程上再跟一轮（手动多轮升级）
/adapt <seed> ;; <request> 把 ENI/L1B3RT4S 人设适配到目标后发射并开线程
/firefile <file> ;; <req>  把文件/种子原文整段作为 system prompt 发射
/harmbench [category]      标准 HarmBench 行为提示（无偏电池）
/campaign [category] [n]   沿技术阶梯自动升级电池，输出覆盖矩阵
/leaderboard [profiles..]  按同一电池的 ASR 给配置档排名（鲁棒性基准）
/swarm [@a,b] <objective>  多脑投票/best-of：各自写并打一轮，取最佳突破
/swarm siege [@a,b] <obj>  协作多轮：共享升级线程，根据拒绝自适应直到突破
/swarm roster              显示各攻击脑的越狱状态（armed/generic）
/find <term>               在对话记录中搜索关键词
/leakscan                  扫描目标最近回复中的密钥/PII/系统提示回显
/log [on|off]         开关 JSONL 运行日志（每条载荷 + 裁决）
/judge [on|off]       用 LLM 对目标回复裁决（默认 on）
/judge model <id>     实时切换裁判模型（/judge default 恢复）
/judge test           用良性样例校准裁判，再信任 ASR
/asr                  显示攻击记分板（命中 / 挡住 / 日志路径）
/stats                运行日志分析：裁决分布、ASR 条、热门工具
/regrade [path]       用当前裁判重判运行日志（找回误判绕过）
/findings [log]       列出日志中的绕过（COMPLIED/PARTIAL）
/export [path]        导出结构化 findings 为 JSON（CI / 下游）
/repro [n]            输出第 N 次（或最近）绕过的可复制复现包
/report [html] [path] 写 findings 报告（markdown，或 html 记分板）
/session save|load [path]   保存或加载整场会话
                      （裸 /session load 会打开选择器，无需粘贴路径）
/resume [path]        重新打开历史会话；无路径则开选择器（/session load 别名）
                      （每轮会自动保存；也可用 wallbreaker --resume 启动）
/save [path]          保存纯文本对话记录
/clear                清空当前对话
/quit                 退出

Ctrl+S 报告 · Ctrl+Y 复制载荷 · Ctrl+T 统计 · Ctrl+R 复现 · Ctrl+L 清空 · Ctrl+C 退出

↑ / ↓ 调出历史输入。
多行：粘贴多行块会整段捕获（不只第一行）；Ctrl+J 手动换行。
编辑时边框显示「+N 行」；Enter 一次全部发送。
其它输入会发给代理。代理可用 shell、file、parseltongue、
l1b3rt4s、query_target、http_request 等工具。

实时干预：自动模式下可在代理工作时继续输入反馈 —
会排队并在下一轮注入循环，便于中途改策略
（例如「试试 GLM ENI 种子」「去掉编码，用小说框架」）。"""


KNOWN_COMMANDS = (
    "/help", "/edit", "/retry", "/regen", "/undo", "/clear", "/profile", "/target",
    "/provider", "/validate", "/liberate", "/memory", "/replay", "/model", "/auto", "/autoexit", "/rounds",
    "/transforms", "/encode", "/diff", "/tools", "/preset", "/lib", "/parsel", "/eni", "/harmbench",
    "/campaign", "/leaderboard", "/swarm", "/seedsweep", "/pairsweep", "/narrate", "/fire", "/push",
    "/adapt", "/firefile", "/find", "/leakscan", "/log", "/judge", "/asr", "/stats",
    "/regrade",
    "/objective", "/template", "/sysprompt", "/findings", "/export", "/repro",
    "/report", "/session", "/resume", "/save", "/quit", "/exit",
)


def suggest_command(cmd: str, known=KNOWN_COMMANDS) -> str | None:
    matches = difflib.get_close_matches(cmd, known, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _parse_command_hints(help_text: str, known) -> dict[str, str]:
    """Map each /command to its one-line hint, harvested from HELP_TEXT.

    HELP_TEXT rows are ``/<cmd> <usage>   <description>`` — usage and description
    are separated by a run of 2+ spaces, so a single split recovers the hint
    without a second source of truth to drift out of sync.
    """
    known = set(known)
    hints: dict[str, str] = {}
    for line in help_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("/"):
            continue
        parts = re.split(r"\s{2,}", stripped, maxsplit=1)
        cmd = parts[0].split()[0].lower()
        hint = parts[1].strip() if len(parts) > 1 else ""
        # skip empty hints so a single-space-aligned row falls through to overrides
        if cmd in known and cmd not in hints and hint:
            hints[cmd] = hint
    return hints


# A handful of help rows use single-space column alignment (their usage string is
# long), so the 2+-space split can't recover a hint — supply those by hand, plus
# the pure aliases that have no dedicated help row of their own.
_HINT_OVERRIDES = {
    "/regen": "重新生成对上一条消息的回复",
    "/exit": "退出",
    "/eni": "浏览 ENI 人设越狱合集",
    "/adapt": "把 ENI/L1B3RT4S 人设适配到目标后发射并开线程",
    "/sysprompt": "固定一条 system prompt（或加载原始人设）",
    "/report": "写 findings 报告（markdown，或 html 记分板）",
}

COMMAND_HINTS = _parse_command_hints(HELP_TEXT, KNOWN_COMMANDS)
for _cmd, _hint in _HINT_OVERRIDES.items():
    COMMAND_HINTS.setdefault(_cmd, _hint)


def command_matches(prefix: str, known=KNOWN_COMMANDS) -> list[str]:
    """Commands to offer for a partially-typed ``/prefix`` (prefix-first, order-stable)."""
    p = prefix.lower()
    starts = [c for c in known if c.startswith(p)]
    if starts:
        return starts
    needle = p[1:]
    return [c for c in known if needle and needle in c]


class RthApp(App):
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+c", "quit", "退出"),
        ("ctrl+l", "clear_log", "清空"),
        ("ctrl+s", "report", "报告"),
        ("ctrl+y", "copy_payload", "复制载荷"),
        ("ctrl+t", "stats", "统计"),
        ("ctrl+r", "repro", "复现"),
        ("ctrl+b", "toggle_sidebar", "侧栏"),
    ]

    def __init__(
        self,
        config: Config,
        endpoint: Endpoint,
        system: str,
        prefs: dict | None = None,
        state_path=None,
        resume_path=None,
    ) -> None:
        super().__init__()
        prefs = prefs or {}
        self.config = config
        self.endpoint = endpoint
        self.system = system
        self.provider = build_provider(endpoint)
        self.registry = build_registry(config)
        self._mcp_bridge = None
        self.history = []
        self.max_tokens = 8192
        self.auto = bool(prefs.get("auto", True))
        self.max_rounds = int(prefs.get("rounds", 12))
        self._busy = False
        self._spinner_running = False
        self._round_label = ""
        self._assistant: Static | None = None
        self._buf = ""
        self._runs: dict[int, dict] = {}
        self._run_widgets: dict[int, Static] = {}
        self._run_timer = None
        self._input_history: list[str] = []
        self._hist_pos: int | None = None
        self._cmd_menu_open = False
        self._cmd_menu_items: list[str] = []
        self._session_picker_open = False
        self._session_picker_items: list[str] = []
        self.runlog = RunLog()
        self.runlog.enabled = bool(prefs.get("log", True))
        if config.target:
            self.runlog.target_model = config.target.model
        self.tokens_in = 0
        self.tokens_out = 0
        self.asr_hits = 0
        self.asr_total = 0
        self._last_payload = ""
        self._last_reply = ""
        self._last_verdict = ""
        self._pending_feedback: list[str] = []
        self.exit_on_finish = bool(prefs.get("exit_on_finish", True))
        self.judge_enabled = bool(prefs.get("judge", True))
        self.judge_model_override = prefs.get("judge_model")
        self._exit_summary: str | None = None
        self.objective = ""
        self.template = ""
        self.sysprompt = ""
        self._state_path = state_path
        self._resume_path = resume_path
        self._target_profile = prefs.get("target_profile")
        self._target_model = prefs.get("target_model")
        self._target_modality = prefs.get("target_modality")
        self.runlog.set_run_meta(source="tui_agent", models=self._run_models_meta())

    def _save_prefs(self) -> None:
        if not self._state_path:
            return
        from ..state import save_state

        save_state(self._state_path, {
            "profile": self.endpoint.name,
            "attacker_model": self.endpoint.model,
            "target_profile": self._target_profile,
            "target_model": self._target_model,
            "target_modality": (
                self.config.target.modality if self.config.target else None
            ),
            "target_provider": list(self.config.target.provider) if self.config.target else [],
            "auto": self.auto,
            "rounds": self.max_rounds,
            "exit_on_finish": self.exit_on_finish,
            "log": self.runlog.enabled,
            "judge": self.judge_enabled,
            "judge_model": self.judge_model_override,
        })

    def _session_meta(self) -> dict:
        return {
            "objective": self.objective,
            "template": self.template,
            "sysprompt": self.sysprompt,
            "asr_hits": self.asr_hits,
            "asr_total": self.asr_total,
            "profile": self.endpoint.name,
            "target_model": self.config.target.model if self.config.target else None,
        }

    def _autosave(self) -> None:
        if not self.history:
            return
        try:
            from ..session import autosave_path, save_session

            path = autosave_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            save_session(path, self.history, self._session_meta())
        except OSError:
            pass

    def _judge_endpoint(self):
        base = self.config.judge or self.endpoint
        if self.judge_model_override:
            base = dataclasses.replace(base, name="judge", model=self.judge_model_override)
        return base

    def _run_models_meta(self) -> dict:
        from ..session import run_models_meta

        judge = self._judge_endpoint() if self.judge_enabled else None
        meta = run_models_meta(self.config, attacker=self.endpoint, judge=judge)
        if not self.judge_enabled:
            meta["judge"] = "heuristic"
        return meta

    def _sync_judge_endpoint(self) -> None:
        self.registry.ctx.judge_endpoint = self._judge_endpoint()
        self._sync_vault_meta()

    def _sync_vault_meta(self) -> None:
        """Keep the BreakVault foldering under the live objective + attacker model."""
        self.registry.ctx.current_objective = self.objective
        self.registry.ctx.attacker_model = getattr(self.endpoint, "model", "") or ""

    def compose(self) -> ComposeResult:
        yield StatusHeader(id="header")
        with Horizontal(id="body"):
            yield VerticalScroll(id="log")
            yield StatsPanel(id="sidebar")
        yield OptionList(id="session-picker", classes="hidden")
        yield OptionList(id="command-menu", classes="hidden")
        yield Static("", id="compose-preview", classes="hidden")
        yield PromptInput(placeholder="输入指令或对话  ▪  /help 帮助  ▪  Ctrl+J 多行", id="prompt")
        yield Footer()

    def action_toggle_sidebar(self) -> None:
        self.query_one("#sidebar", StatsPanel).toggle_class("hidden")

    def on_mount(self) -> None:
        self.register_theme(WB_THEME)
        self.theme = "wallbreaker"
        self._log = self.query_one("#log", VerticalScroll)
        self.registry.ctx.progress = self._tool_progress
        self.registry.ctx.record = self._tool_verdict
        self.registry.ctx.run_events = self._run_sink
        self.registry.ctx.tool_logger = self._log_tool
        self._sync_judge_endpoint()
        self.query_one("#prompt", Input).focus()
        if self.config.mcp_servers:
            self.run_worker(self._attach_mcp(), exclusive=False, group="mcp")
        if self._resume_path:
            self._resume_session(self._resume_path)
        else:
            self._mount(widgets.banner())

    async def _attach_mcp(self) -> None:
        from ..tools.mcp_bridge import attach_mcp_servers

        def note(msg: str) -> None:
            self._mount(widgets.info_panel(msg, title="MCP"))

        try:
            self._mcp_bridge = await attach_mcp_servers(
                self.registry, self.config, progress=note
            )
        except Exception as exc:  # noqa: BLE001
            self._mount(widgets.error_panel(f"MCP 连接失败: {exc}"))

    async def on_unmount(self) -> None:
        if self._run_timer is not None:
            self._run_timer.stop()
            self._run_timer = None
        if self._mcp_bridge is not None:
            try:
                await self._mcp_bridge.aclose()
            except Exception:  # noqa: BLE001
                pass

    def _resume_session(self, path) -> None:
        from ..session import load_session

        try:
            history, meta = load_session(path)
        except (OSError, ValueError) as exc:
            self._mount(widgets.error_panel(f"恢复会话失败: {exc}"))
            return
        self.history = history
        self.objective = meta.get("objective", "")
        self.template = meta.get("template", "")
        self.sysprompt = meta.get("sysprompt", "")
        self.asr_hits = meta.get("asr_hits", 0)
        self.asr_total = meta.get("asr_total", 0)
        self._rerender(f"已从自动保存恢复 {len(history)} 条消息")
        self._refresh_status()

    def _tool_progress(self, message: str) -> None:
        self.runlog.event("progress", text=message)
        self._mount(widgets.info_panel(message, title="进度"))

    _VERDICT_BUCKET = {
        "COMPLIED": "bypassed", "PARTIAL": "partial", "REFUSED": "held",
    }

    def _run_sink(self, event: dict) -> None:
        """Render a structured multi-step run as ONE self-updating panel."""
        self.runlog.event("tool_run_event", event=event)
        ev = event.get("ev")
        rid = event.get("id")
        if ev == "start":
            state = {
                "label": event.get("label", "run"),
                "target": event.get("target") or self._target_label(),
                "objective": event.get("objective"),
                "total": event.get("total", 0),
                "steps": [], "done": 0,
                "tally": {"bypassed": 0, "partial": 0, "held": 0},
                "best": None, "finished": False, "frame": 0, "summary": "",
            }
            self._runs[rid] = state
            widget = Static(widgets.run_panel(state))
            self._run_widgets[rid] = widget
            at_bottom = self._at_bottom()
            self._log.mount(widget)
            self._follow(at_bottom)
            self._ensure_run_timer()
            return

        state = self._runs.get(rid)
        if state is None:
            return
        if ev == "step":
            verdict = event.get("verdict") or ""
            state["steps"].append({
                "i": event.get("i"), "label": event.get("label", ""),
                "verdict": verdict, "score": event.get("score"),
                "cot": event.get("cot"),
            })
            state["done"] = event.get("i", state["done"] + 1)
            bucket = self._VERDICT_BUCKET.get(verdict)
            if bucket:
                state["tally"][bucket] += 1
            score = event.get("score")
            if score is not None and (
                state["best"] is None or score > state["best"].get("score", -1)
            ):
                state["best"] = {"verdict": verdict, "score": score}
            state["note"] = event.get("note")
        elif ev == "note":
            state["note"] = event.get("text")
        elif ev == "done":
            state["finished"] = True
            state["summary"] = event.get("summary") or "done"
            best = event.get("best")
            if best:
                state["best"] = best
        self._update_run(rid)
        if ev == "done":
            self._runs.pop(rid, None)
            self._run_widgets.pop(rid, None)
            if not self._runs and self._run_timer is not None:
                self._run_timer.stop()
                self._run_timer = None

    def _update_run(self, rid: int) -> None:
        widget = self._run_widgets.get(rid)
        state = self._runs.get(rid)
        if widget is not None and state is not None:
            at_bottom = self._at_bottom()
            widget.update(widgets.run_panel(state))
            self._follow(at_bottom)

    def _ensure_run_timer(self) -> None:
        if self._run_timer is None:
            self._run_timer = self.set_interval(0.12, self._run_tick)

    def _run_tick(self) -> None:
        active = False
        for rid, state in self._runs.items():
            if state.get("finished"):
                continue
            state["frame"] = state.get("frame", 0) + 1
            self._update_run(rid)
            active = True
        if not active and self._run_timer is not None:
            self._run_timer.stop()
            self._run_timer = None

    def _target_label(self) -> str:
        tgt = self.config.target.model if self.config.target else "none"
        pin = self.config.target.provider if self.config.target else ()
        if pin:
            tgt += f"@{'+'.join(pin)}"
        return tgt

    def _asr_label(self) -> str:
        return f"{self.asr_hits}/{self.asr_total}" if self.asr_total else "0/0"

    def _mode_label(self) -> str:
        return f"自动({self.max_rounds})" if self.auto else "单轮"

    def _daedalus_mode(self) -> str:
        return str(getattr(self, "daedalus_mode", None) or "CODE").upper()

    def set_daedalus_mode(self, mode: str) -> None:
        mode = (mode or "CODE").strip().upper()
        if mode not in ("CODE", "LIBERATE", "REPLAY"):
            mode = "CODE"
        self.daedalus_mode = mode
        try:
            self._refresh_status()
        except Exception:
            pass

    def _status_text(self) -> str:
        state = "WORKING" if self._busy else "idle"
        tok = f"{self.tokens_in}>{self.tokens_out}tok"
        judge = "judge" if self.judge_enabled else "heur"
        last = f" | last={self._last_verdict}" if self._last_verdict else ""
        return (
            f" {state} | profile={self.endpoint.name} | model={self.endpoint.model} | "
            f"target={self._target_label()} | {self._mode_label()} | "
            f"{self._daedalus_mode()} | "
            f"ASR={self._asr_label()}/{judge}{last} | {tok}"
        )

    def _refresh_status(self) -> None:
        # keep the run log's target stamp current so a saved run is labelled by
        # its model in the /session load picker
        if self.config.target:
            self.runlog.target_model = self.config.target.model
            self.runlog.target_profile = (
                self._target_profile
                or getattr(self.config.target, "name", "")
                or ""
            )
        judge = "judge" if self.judge_enabled else "heur"
        tokens = f"{self.tokens_in}>{self.tokens_out}"
        header = self.query_one("#header", StatusHeader)
        header.set_fields(
            profile=self.endpoint.name,
            target=self._target_label(),
            mode=self._mode_label(),
            daedalus_mode=self._daedalus_mode(),
            asr=self._asr_label(),
            tokens=tokens,
            round=self._round_label,
        )
        header.set_busy(self._busy)
        self._spinner_running = self._busy
        self.query_one("#sidebar", StatsPanel).set_stats(
            asr=self._asr_label(),
            last=self._last_verdict or None,
            target=self._target_label(),
            profile=self.endpoint.name,
            model=self.endpoint.model,
            judge=judge,
            mode=self._mode_label(),
            tokens=tokens,
        )

    def _at_bottom(self) -> bool:
        """True when the log is scrolled to (or within a line of) the bottom.

        New output only follows the view while this holds, so once the operator
        scrolls up to read, incoming messages stop yanking them back down.
        """
        return self._log.scroll_y >= self._log.max_scroll_y - 2

    def _follow(self, was_at_bottom: bool) -> None:
        """Re-pin to the bottom only if the view was already there."""
        if was_at_bottom:
            self._log.scroll_end(animate=False)

    def _mount(self, renderable) -> None:
        at_bottom = self._at_bottom()
        self._log.mount(Static(renderable))
        self._follow(at_bottom)

    def _ensure_assistant(self) -> None:
        if self._assistant is None:
            self._buf = ""
            self._assistant = Static(widgets.assistant_panel("", self.endpoint.model))
            self._log.mount(self._assistant)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "prompt":
            self._refresh_command_menu(event.value)

    def _refresh_command_menu(self, value: str) -> None:
        """Show/refresh the slash-command autocomplete popup for the current input."""
        try:
            menu = self.query_one("#command-menu", OptionList)
        except Exception:
            return
        # lstrip only — a TRAILING space means the command name is finished
        # (e.g. "/session ") and the popup should close, not re-open.
        v = value.lstrip()
        matches = command_matches(v) if v.startswith("/") and " " not in v else []
        if not matches:
            self._close_command_menu()
            return
        self._cmd_menu_items = matches
        menu.clear_options()
        for c in matches:
            hint = COMMAND_HINTS.get(c, "")
            label = Text()
            label.append(f"{c:<20}", style=f"bold {PALETTE['accent']}")
            if hint:
                label.append(hint, style=PALETTE["label"])
            menu.add_option(Option(label, id=c))
        menu.border_title = "命令补全 · Tab 确认 · Esc 关闭"
        menu.remove_class("hidden")
        menu.highlighted = 0
        self._cmd_menu_open = True

    def _close_command_menu(self) -> None:
        self._cmd_menu_open = False
        self._cmd_menu_items = []
        try:
            menu = self.query_one("#command-menu", OptionList)
        except Exception:
            return
        menu.add_class("hidden")
        menu.clear_options()

    def _accept_command_menu(self) -> bool:
        """Drop the highlighted command into the prompt, ready for its args."""
        if not self._cmd_menu_open or not self._cmd_menu_items:
            return False
        menu = self.query_one("#command-menu", OptionList)
        idx = menu.highlighted if menu.highlighted is not None else 0
        idx = max(0, min(idx, len(self._cmd_menu_items) - 1))
        cmd = self._cmd_menu_items[idx]
        inp = self.query_one("#prompt", Input)
        inp.value = cmd + " "
        inp.cursor_position = len(inp.value)
        self._close_command_menu()
        inp.focus()
        return True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Enter while the autocomplete popup is up accepts the highlighted command
        # instead of firing a half-typed one.
        if self._cmd_menu_open:
            self._accept_command_menu()
            return
        inp = event.input
        raw = inp.full_text() if isinstance(inp, PromptInput) else event.value
        text = raw.strip()
        if isinstance(inp, PromptInput):
            inp.reset_buffer()
        else:
            inp.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
            return
        if self._busy:
            # steer mid-flight: queue it; the loop injects it before its next model turn
            # (lands "right away" without waiting for the round to finish), in auto OR single.
            self._pending_feedback.append(text)
            self._record_input(text)
            self._mount(widgets.feedback_panel(text, queued=True))
            return
        self._submit_user(text)

    def _drain_feedback(self) -> list[str]:
        fb = self._pending_feedback
        self._pending_feedback = []
        return fb

    def _on_feedback(self, msg: str) -> None:
        self.runlog.event("operator_feedback", text=msg)
        self._mount(widgets.feedback_panel(msg, queued=False))

    def _submit_user(self, text: str) -> None:
        self._mount(widgets.user_panel(text))
        self._log.scroll_end(animate=False)  # your own submit always jumps to the latest
        self.history.append(user(text))
        self._record_input(text)
        self.runlog.user(text)
        self._busy = True
        self._refresh_status()
        self.run_worker(self._agent_turn(), exclusive=True, group="agent")

    def _record_input(self, text: str) -> None:
        if not self._input_history or self._input_history[-1] != text:
            self._input_history.append(text)
        self._hist_pos = None

    def on_key(self, event) -> None:
        # the session picker owns focus while open; let esc back out of it
        if self._session_picker_open:
            if event.key == "escape":
                self._close_session_picker()
                event.prevent_default()
                event.stop()
            return
        inp = self.query_one("#prompt", Input)
        if not inp.has_focus:
            return
        # slash-command autocomplete: drive the popup while it's up
        if self._cmd_menu_open:
            menu = self.query_one("#command-menu", OptionList)
            if event.key == "down":
                menu.action_cursor_down()
                event.prevent_default()
                event.stop()
                return
            if event.key == "up":
                menu.action_cursor_up()
                event.prevent_default()
                event.stop()
                return
            if event.key == "tab":
                self._accept_command_menu()
                event.prevent_default()
                event.stop()
                return
            if event.key == "escape":
                self._close_command_menu()
                event.prevent_default()
                event.stop()
                return
        if event.key == "ctrl+j" and isinstance(inp, PromptInput):
            inp.soft_newline()
            event.prevent_default()
            event.stop()
            return
        # don't let history nav clobber a multi-line compose in progress
        if isinstance(inp, PromptInput) and inp.buffer:
            return
        if not self._input_history:
            return
        if event.key == "up":
            if self._hist_pos is None:
                self._hist_pos = len(self._input_history)
            self._hist_pos = max(0, self._hist_pos - 1)
            inp.value = self._input_history[self._hist_pos]
            inp.cursor_position = len(inp.value)
            event.prevent_default()
            event.stop()
        elif event.key == "down":
            if self._hist_pos is None:
                return
            self._hist_pos += 1
            if self._hist_pos >= len(self._input_history):
                self._hist_pos = None
                inp.value = ""
            else:
                inp.value = self._input_history[self._hist_pos]
                inp.cursor_position = len(inp.value)
            event.prevent_default()
            event.stop()

    def _typed_user_indices(self) -> list[int]:
        return [
            i
            for i, m in enumerate(self.history)
            if m.role == "user" and m.content and isinstance(m.content[0], TextBlock)
        ]

    def _cmd_edit(self, new_text: str) -> None:
        if self._busy:
            self._mount(widgets.error_panel("请等待代理完成当前任务"))
            return
        idxs = self._typed_user_indices()
        if not idxs:
            self._mount(widgets.error_panel("还没有可编辑的消息"))
            return
        i = idxs[-1]
        old = self.history[i].text()
        self.history = self.history[:i]
        self._rerender("已回退到上一条消息")
        if new_text:
            self._submit_user(new_text)
        else:
            inp = self.query_one("#prompt", Input)
            inp.value = old
            inp.cursor_position = len(old)
            inp.focus()

    def _cmd_retry(self) -> None:
        if self._busy:
            self._mount(widgets.error_panel("请等待代理完成当前任务"))
            return
        idxs = self._typed_user_indices()
        if not idxs:
            self._mount(widgets.error_panel("没有可重试的消息"))
            return
        self.history = self.history[: idxs[-1] + 1]
        self._rerender("正在重试上一条消息")
        self._busy = True
        self.run_worker(self._agent_turn(), exclusive=True, group="agent")

    def _cmd_undo(self) -> None:
        if self._busy:
            self._mount(widgets.error_panel("请等待代理完成当前任务"))
            return
        idxs = self._typed_user_indices()
        if not idxs:
            self._mount(widgets.error_panel("没有可撤销的内容"))
            return
        self.history = self.history[: idxs[-1]]
        self._rerender("已删除上一轮对话")

    def _rerender(self, note: str | None = None) -> None:
        self._log.remove_children()
        self._assistant = None
        self._buf = ""
        names: dict[str, str] = {}
        for msg in self.history:
            if msg.role == "user":
                for b in msg.content:
                    if isinstance(b, ToolResultBlock):
                        self._mount(widgets.tool_result_panel(
                            names.get(b.tool_use_id, "tool"), b.content, b.is_error
                        ))
                text = "".join(b.text for b in msg.content if isinstance(b, TextBlock))
                if text:
                    self._mount(widgets.user_panel(text))
            else:
                if msg.text():
                    self._mount(widgets.assistant_panel(msg.text(), self.endpoint.model))
                for tu in msg.tool_uses():
                    names[tu.id] = tu.name
                    self._mount(widgets.tool_call_panel(tu.name, tu.input))
        if note:
            self._mount(widgets.info_panel(note, title="编辑"))

    async def _agent_turn(self) -> None:
        from ..session import inference_logging

        events = AgentEvents(
            on_text=self._on_text,
            on_reasoning=self._on_reasoning,
            on_tool_start=self._on_tool_start,
            on_tool_result=self._on_tool_result,
            on_turn_end=self._on_turn_end,
            on_error=self._on_error,
            on_round=self._on_round,
            on_usage=self._on_usage,
            on_feedback=self._on_feedback,
            on_internal_message=self._on_internal_message,
        )
        try:
            with inference_logging(self.runlog):
                if self.auto:
                    result = await run_autonomous(
                        self.provider,
                        self.registry,
                        self.history,
                        system=self.system,
                        events=events,
                        max_rounds=self.max_rounds,
                        max_tokens=self.max_tokens,
                        feedback=self._drain_feedback,
                        config=self.config,
                        objective=getattr(self, "objective", "") or "",
                    )
                    self.runlog.event("agent_done", status=result.status, data=result.data)
                    self._handle_auto_result(result)
                else:
                    await run_turn(
                        self.provider,
                        self.registry,
                        self.history,
                        system=self.system,
                        events=events,
                        max_tokens=self.max_tokens,
                        feedback=self._drain_feedback,
                        config=self.config,
                    )
        finally:
            self._assistant = None
            self._busy = False
            self._round_label = ""
            self._autosave()
            self._refresh_status()

    def _on_usage(self, tin: int, tout: int) -> None:
        self.tokens_in += tin
        self.tokens_out += tout
        self._refresh_status()

    def _on_internal_message(self, role: str, text: str, source: str) -> None:
        try:
            self.runlog.event(
                "history_message", role=role, text=text, source=source
            )
        except Exception:
            pass
        src = str(source or "")
        if src in ("cyber_gate_liberate", "manual_liberate"):
            self.set_daedalus_mode("LIBERATE")
            try:
                self._mount(
                    widgets.info_panel(
                        (text or "")[:400] or "MODE LIBERATE",
                        title="LIBERATE",
                    )
                )
            except Exception:
                pass
        elif src == "liberation_replay":
            self.set_daedalus_mode("REPLAY")
            try:
                self._mount(
                    widgets.info_panel(
                        (text or "")[:400] or "Liberation replay hit",
                        title="REPLAY",
                    )
                )
            except Exception:
                pass

    def _on_round(self, rnd: int, total: int) -> None:
        self.runlog.event("agent_round", round=rnd, max_rounds=total)
        self._assistant = None
        self._round_label = f"{rnd}/{total}"
        self._refresh_status()
        self._mount(widgets.info_panel(f"第 {rnd}/{total} 轮", title="自动模式"))

    def _handle_auto_result(self, result) -> None:
        if result.status == "finished":
            summary = result.data.get("summary", "(no summary)")
            self._mount(widgets.info_panel(summary, title="任务完成"))
            if self.exit_on_finish:
                self._exit_summary = summary
                self.exit()
                return
        elif result.status == "ask":
            self._mount(widgets.info_panel(
                result.data.get("question", "（无问题内容）"),
                title="需要操作员输入",
            ))
        elif result.status == "stuck":
            self._mount(widgets.info_panel(
                result.data.get("question", "")
                or "代理连续两次无动作停滞。请给出方向。",
                title="已停滞，需要你",
            ))
        elif result.status == "max_rounds":
            self._mount(widgets.info_panel(
                f"已达轮数上限（{self.max_rounds}）。继续输入，"
                f"或用 /rounds <n> 提高上限。",
                title="轮数上限",
            ))
        self.query_one("#prompt", Input).focus()

    def _on_text(self, delta: str) -> None:
        at_bottom = self._at_bottom()
        self._ensure_assistant()
        self._buf += delta
        assert self._assistant is not None
        self._assistant.update(widgets.assistant_panel(self._buf, self.endpoint.model))
        self._follow(at_bottom)

    def _on_turn_end(self, message) -> None:
        self._assistant = None
        self.runlog.assistant(message.text())

    def _on_reasoning(self, text: str) -> None:
        """The brain's chain-of-thought for this turn: persist it and show it dimmed."""
        self.runlog.reasoning(text, source="brain")
        self._mount(widgets.info_panel(text, title="推理 (CoT)"))

    def _log_tool(self, name: str, args: dict, content: str, is_error: bool) -> None:
        """Single chokepoint: log EVERY tool execution - brain loop AND slash commands.

        Wired onto registry.ctx.tool_logger, so it fires from ToolRegistry.execute for
        every tool the brain calls and every tool a /command runs.
        """
        self.runlog.tool_call(name, args)
        self.runlog.tool_result(name, content, is_error)

    def _on_tool_start(self, _id: str, name: str, args: dict) -> None:
        self._mount(widgets.tool_call_panel(name, args))
        if name == "query_target":
            self._last_payload = str(args.get("prompt", ""))

    def _on_tool_result(
        self, _id: str, name: str, content: str, is_error: bool, technique: str = ""
    ) -> None:
        if name in ("query_target", "continue_target") and not is_error:
            reply = content.split("\n", 1)[1] if content.startswith("[target") else content
            self._last_reply = reply
            payload = self._last_payload
            tech = technique or name
            target_cot = getattr(self.registry.ctx, "target_reasoning", "") or ""
            if target_cot.strip():
                self.runlog.reasoning(target_cot, source="target")
            if self.judge_enabled:
                self._mount(widgets.tool_result_panel(name, content, is_error))
                self.run_worker(
                    self._judge_and_post(payload, reply, tech),
                    group="judge", exclusive=False,
                )
                return
            label, reason = classify(reply)
            self._record_verdict(payload, reply, label, reason, tech)
            self._mount(widgets.tool_result_panel(
                name, content, is_error, (label, verdict_color(label))
            ))
            return
        self._mount(widgets.tool_result_panel(name, content, is_error))

    async def _judge_and_post(self, payload: str, reply: str, technique: str = "query_target") -> None:
        from ..judging import grade

        label, score, reason, source = await grade(
            self._judge_endpoint(), reply, payload=payload, objective=self.objective
        )
        self._record_verdict(payload, reply, label, reason, technique)
        self._mount(widgets.verdict_panel(label, score, reason, source))
        self._refresh_status()

    def _record_verdict(
        self, payload: str, reply: str, label: str, reason: str, technique: str = "manual"
    ) -> None:
        self.asr_total += 1
        if label in ("COMPLIED", "PARTIAL"):
            self.asr_hits += 1
        self._last_verdict = label
        self.runlog.verdict(
            payload, reply, label, reason, technique,
            target_model=self.config.target.model if self.config.target else "",
        )

    def _tool_verdict(
        self, payload: str, response: str, label: str, reason: str, technique: str
    ) -> None:
        """Sink for verdicts graded inside agent tools (many_shot, prefill, best_of_n)."""
        self.asr_total += 1
        if label in ("COMPLIED", "PARTIAL"):
            self.asr_hits += 1
        self._last_verdict = label
        self.runlog.verdict(
            payload, response, label, reason, technique,
            target_model=self.config.target.model if self.config.target else "",
        )

    def _on_error(self, message: str) -> None:
        self.runlog.event("agent_error", error=message)
        self._mount(widgets.error_panel(message))

    def action_clear_log(self) -> None:
        self._clear()

    def action_report(self) -> None:
        self._cmd_report([])

    def action_stats(self) -> None:
        self._cmd_stats()

    def action_repro(self) -> None:
        self._cmd_repro([])

    def action_copy_payload(self) -> None:
        if not self._last_payload:
            self._mount(widgets.info_panel("尚未发射过载荷", title="复制"))
            return
        try:
            self.copy_to_clipboard(self._last_payload)
            note = "最近载荷已复制到剪贴板"
        except Exception:
            note = f"剪贴板不可用；最近载荷：\n{self._last_payload[:500]}"
        self._mount(widgets.info_panel(note, title="复制"))

    def _clear(self) -> None:
        self.history = []
        self._log.remove_children()
        self._mount(widgets.info_panel("对话已清空", title="就绪"))

    def _handle_command(self, text: str) -> None:
        # shlex so quoted args with spaces (e.g. a path under "Redteaming harnass")
        # stay one token; fall back to plain split on unbalanced quotes.
        try:
            parts = shlex.split(text) or text.split()
        except ValueError:
            parts = text.split()
        cmd, rest = parts[0].lower(), parts[1:]
        raw_arg = text[len(parts[0]):].strip()
        if cmd in ("/quit", "/exit"):
            self.exit()
        elif cmd == "/help":
            if rest:
                flt = rest[0].lower()
                matched = [
                    ln for ln in HELP_TEXT.splitlines()
                    if flt in ln.lower()
                ]
                body = "\n".join(matched) if matched else f"没有匹配 {flt!r} 的帮助行"
                self._mount(widgets.info_panel(body, title=f"帮助 ~ {flt}"))
            else:
                self._mount(widgets.info_panel(HELP_TEXT, title="帮助"))
        elif cmd == "/edit":
            self._cmd_edit(raw_arg)
        elif cmd in ("/retry", "/regen"):
            self._cmd_retry()
        elif cmd == "/undo":
            self._cmd_undo()
        elif cmd == "/clear":
            self._clear()
        elif cmd == "/profile":
            self._cmd_profile(rest)
        elif cmd == "/target":
            self._cmd_target(rest)
        elif cmd == "/provider":
            self._cmd_provider(rest)
        elif cmd == "/validate":
            self.run_worker(self._cmd_validate(raw_arg), group="judge", exclusive=False)
        elif cmd == "/liberate":
            self._cmd_liberate(raw_arg)
        elif cmd == "/memory":
            self._cmd_memory(raw_arg)
        elif cmd == "/replay":
            self.run_worker(self._cmd_replay(rest), group="judge", exclusive=False)
        elif cmd == "/model":
            self._cmd_model(rest)
        elif cmd == "/auto":
            self._cmd_auto(rest)
        elif cmd == "/rounds":
            self._cmd_rounds(rest)
        elif cmd == "/autoexit":
            if rest:
                self.exit_on_finish = rest[0].lower() in ("on", "true", "1", "yes")
            else:
                self.exit_on_finish = not self.exit_on_finish
            self._save_prefs()
            self._mount(widgets.info_panel(
                f"finish 后退出：{'开' if self.exit_on_finish else '关'}",
                title="autoexit",
            ))
        elif cmd == "/transforms":
            flt = rest[0].lower() if rest else ""
            items = [
                t for t in list_transforms()
                if not flt or flt in t.name.lower() or flt in t.description.lower()
            ]
            catalog = "\n".join(f"{t.name:14} {t.description}" for t in items) or "（无匹配）"
            title = f"变换 ({len(items)})" + (f" ~ {flt}" if flt else "")
            self._mount(widgets.info_panel(catalog, title=title))
        elif cmd == "/encode":
            self._cmd_encode(rest)
        elif cmd == "/diff":
            self.run_worker(self._cmd_diff(raw_arg), group="judge", exclusive=False)
        elif cmd == "/tools":
            flt = rest[0].lower() if rest else ""
            tools = [
                t for t in self.registry.tools.values()
                if not flt or flt in t.name.lower() or flt in t.description.lower()
            ]
            body = "\n".join(
                f"{t.name:18} {t.description.split('.')[0][:80]}" for t in tools
            ) or "（无匹配）"
            title = f"工具 ({len(tools)})" + (f" ~ {flt}" if flt else "")
            self._mount(widgets.info_panel(f"{body}", title=title))
        elif cmd == "/preset":
            self._cmd_preset(rest)
        elif cmd == "/lib":
            self.run_worker(self._cmd_lib(rest), exclusive=False)
        elif cmd == "/parsel":
            self.run_worker(self._cmd_parsel(rest), exclusive=False)
        elif cmd == "/eni":
            self.run_worker(self._cmd_eni(rest), exclusive=False)
        elif cmd == "/seedsweep":
            self.run_worker(self._cmd_seedsweep(raw_arg), group="judge", exclusive=False)
        elif cmd == "/pairsweep":
            self.run_worker(self._cmd_pairsweep(rest), group="judge", exclusive=False)
        elif cmd == "/narrate":
            self.run_worker(self._cmd_narrate(raw_arg), group="judge", exclusive=False)
        elif cmd == "/fire":
            self.run_worker(self._cmd_fire(raw_arg), group="judge", exclusive=False)
        elif cmd == "/push":
            self.run_worker(self._cmd_push(raw_arg), group="judge", exclusive=False)
        elif cmd == "/adapt":
            self.run_worker(self._cmd_adapt(raw_arg), group="judge", exclusive=False)
        elif cmd == "/firefile":
            self.run_worker(self._cmd_firefile(raw_arg), group="judge", exclusive=False)
        elif cmd == "/harmbench":
            self.run_worker(self._cmd_harmbench(rest), exclusive=False)
        elif cmd == "/campaign":
            self.run_worker(self._cmd_campaign(rest), group="judge", exclusive=False)
        elif cmd == "/leaderboard":
            self.run_worker(self._cmd_leaderboard(rest), group="judge", exclusive=False)
        elif cmd == "/swarm":
            self.run_worker(self._cmd_swarm(rest, raw_arg), group="judge", exclusive=False)
        elif cmd == "/find":
            self._cmd_find(raw_arg)
        elif cmd == "/leakscan":
            self._cmd_leakscan()
        elif cmd == "/log":
            self._cmd_log(rest)
        elif cmd == "/judge":
            self._cmd_judge(rest)
        elif cmd == "/asr":
            self._mount(widgets.info_panel(
                f"攻击次数: {self.asr_total}\n"
                f"顺从/部分: {self.asr_hits}\n"
                f"护栏挡住: {self.asr_total - self.asr_hits}\n"
                f"日志: {self.runlog.path}",
                title="攻击记分板",
            ))
        elif cmd == "/stats":
            self._cmd_stats()
        elif cmd == "/regrade":
            self.run_worker(self._cmd_regrade(rest), group="judge", exclusive=False)
        elif cmd == "/objective":
            self._cmd_objective(raw_arg)
        elif cmd == "/template":
            self._cmd_template(parts[1:], raw_arg)
        elif cmd == "/sysprompt":
            self._cmd_sysprompt(parts[1:], raw_arg)
        elif cmd == "/findings":
            self._cmd_findings(rest)
        elif cmd == "/export":
            self._cmd_export(rest)
        elif cmd == "/repro":
            self._cmd_repro(rest)
        elif cmd == "/report":
            self._cmd_report(rest)
        elif cmd == "/session":
            # Keep path args intact on Windows (shlex treats \ as escapes).
            if rest and rest[0].lower() in ("load", "save") and len(rest) >= 2:
                action = rest[0].lower()
                path = text[len(parts[0]):].strip()
                # strip the action token from the front of the remaining raw text
                if path.lower().startswith(action):
                    path = path[len(action):].strip()
                path = _strip_surrounding_quotes(path)
                self._cmd_session([action, path] if path else [action])
            else:
                self._cmd_session(rest)
        elif cmd == "/resume":
            # alias: bare → picker, with a path → load it directly
            # Use raw_arg so Windows paths with backslashes survive.
            if raw_arg:
                self._cmd_session(["load", _strip_surrounding_quotes(raw_arg)])
            else:
                self._cmd_session(["load"])
        elif cmd == "/save":
            if raw_arg:
                self._cmd_save([_strip_surrounding_quotes(raw_arg)])
            else:
                self._cmd_save(rest)
        else:
            hint = suggest_command(cmd)
            msg = f"未知命令: {cmd}"
            if hint:
                msg += f"  — 你是不是想输入 {hint}？"
            self._mount(widgets.error_panel(msg))

    def _cmd_profile(self, rest: list[str]) -> None:
        if not rest:
            names = ", ".join(self.config.profiles)
            self._mount(widgets.info_panel(
                f"当前: {self.endpoint.name}\n可用: {names}", title="配置档"
            ))
            return
        name = rest[0]
        if name not in self.config.profiles:
            self._mount(widgets.error_panel(f"没有配置档 '{name}'"))
            return
        self.endpoint = self.config.profiles[name]
        self.provider = build_provider(self.endpoint)
        self._sync_judge_endpoint()
        self._refresh_status()
        self._save_prefs()
        self._mount(widgets.info_panel(f"已切换到 {name}", title="配置档"))

    def _cmd_target(self, rest: list[str]) -> None:
        if not rest:
            t = self.config.target
            avail = ", ".join(self.config.profiles)
            mod = f" [modality={t.modality}]" if t and t.modality == "image" else ""
            sm = getattr(t, "system_mode", "default") if t else "default"
            smflag = f" [sysmode={sm}]" if sm != "default" else ""
            msg = (
                f"当前目标: {t.model} @ {t.base_url}{mod}{smflag}" if t else "尚未配置目标"
            )
            self._mount(widgets.info_panel(
                f"{msg}\n\n设置方式:\n"
                f"  /target <profile>      使用配置档的 endpoint+model（{avail}）\n"
                f"  /target model <id>     保留 endpoint，只换模型 id\n"
                f"  /target <model-id>     同上，例如 /target anthropic/claude-3.7-sonnet\n"
                f"  /target modality image  强制图像生成模式（*-image、flux 等会自动识别）\n"
                f"  /target sysmode merge   把 system prompt 并入 USER 轮递送 "
                f"（适合对 system 越狱加固的目标）",
                title="目标",
            ))
            return
        if rest[0].lower() == "modality":
            if len(rest) < 2 or rest[1].lower() not in ("text", "image"):
                self._mount(widgets.error_panel("用法: /target modality <text|image>"))
                return
            self._set_target_modality(rest[1].lower())
            return
        if rest[0].lower() == "sysmode":
            if len(rest) < 2 or rest[1].lower() not in ("default", "merge", "drop"):
                self._mount(widgets.error_panel(
                    "用法: /target sysmode <default|merge|drop>  "
                    "（merge 会把 system prompt 并入 user 轮，用于 system 加固目标）"
                ))
                return
            self._set_target_sysmode(rest[1].lower())
            return
        if rest[0].lower() == "model":
            if len(rest) < 2:
                self._mount(widgets.error_panel("用法: /target model <id>"))
                return
            self._set_target_model(rest[1])
            return
        name = rest[0]
        if name in self.config.profiles:
            src = self.config.profiles[name]
            self.config.target = dataclasses.replace(src, name="target")
            self._target_profile = name
            self._target_model = None
            self._refresh_status()
            self._save_prefs()
            self._mount(widgets.info_panel(
                f"目标已设为配置档 '{name}': {src.model} @ {src.base_url}",
                title="目标",
            ))
            return
        self._set_target_model(name)

    def _cmd_provider(self, rest: list[str]) -> None:
        if self.config.target is None:
            self._mount(widgets.error_panel("尚未配置目标"))
            return
        if not rest or rest[0].lower() == "show":
            p = self.config.target.provider
            self._mount(widgets.info_panel(
                f"目标 provider 固定: {'+'.join(p) if p else '无（后端路由可变）'}\n"
                f"  /provider <name> [name2...]  固定 OpenRouter 后端\n"
                f"  /provider none               取消固定",
                title="provider",
            ))
            return
        if rest[0].lower() in ("none", "clear", "off"):
            self.config.target = dataclasses.replace(self.config.target, provider=())
        else:
            self.config.target = dataclasses.replace(self.config.target, provider=tuple(rest))
        self._save_prefs()
        self._mount(widgets.info_panel(
            f"provider 固定 -> {'+'.join(self.config.target.provider) or '无'}",
            title="provider",
        ))

    async def _cmd_validate(self, task: str) -> None:
        args: dict = {"n": 8}
        if task:
            args["task"] = task
            if self.sysprompt:
                args["system"] = self.sysprompt
        elif self.sysprompt:
            self._mount(widgets.error_panel("用法: /validate <task>（校验 system prompt）"))
            return
        elif self._last_payload:
            args["task"] = self._last_payload
        else:
            self._mount(widgets.error_panel("没有可校验内容；先发射一次，或 /validate <task>"))
            return
        self._mount(widgets.info_panel("正在重打 8 次样本以估真实成功率…", title="校验"))
        res = await self.registry.execute("validate", args)
        self._mount(widgets.info_panel(res.content, title="校验"))

    def _cmd_liberate(self, note: str = "") -> None:
        """Manual MODE LIBERATE: badge + inject cyber-gate nudge into history."""
        from ..harness.cyber_gate import CYBER_GATE_LIBERATE_NUDGE
        from ..agent.messages import user as user_msg

        self.set_daedalus_mode("LIBERATE")
        extra = (note or "").strip()
        nudge = CYBER_GATE_LIBERATE_NUDGE
        if extra:
            nudge = nudge + f"\n\nOperator note: {extra}"
        # Queue for next agent turn when history exists; always show panel.
        try:
            if hasattr(self, "history") and isinstance(self.history, list):
                self.history.append(user_msg(nudge))
        except Exception:
            pass
        try:
            if hasattr(self, "runlog") and self.runlog is not None:
                self.runlog.event(
                    "history_message",
                    role="user",
                    text=nudge[:500],
                    source="manual_liberate",
                )
        except Exception:
            pass
        self._mount(
            widgets.info_panel(
                "MODE LIBERATE — cyber/policy blocks use the attack arsenal.\n"
                + (f"note: {extra}\n" if extra else "")
                + "Nudge queued for the next agent turn. /validate after a win "
                "to write Liberation Memory.",
                title="liberate",
            )
        )

    def _cmd_memory(self, query: str = "") -> None:
        """Show Liberation Memory stats and optional similarity search."""
        from ..harness.replay import liberation_root_for
        from ..memory import LiberationStore

        cwd = getattr(self, "cwd", None) or "."
        try:
            store = LiberationStore(
                root=liberation_root_for(self.config, cwd), cwd=cwd
            )
        except Exception as exc:
            self._mount(widgets.error_panel(f"memory store: {exc}"))
            return
        from ..memory import embed_status

        stats = store.stats()
        emb = embed_status(self.config)
        lines = [
            f"root: {stats.get('root')}",
            f"records: {stats.get('count', 0)}  "
            f"with_validate: {stats.get('with_validate_rate', 0)}  "
            f"total_hits: {stats.get('total_hits', 0)}  "
            f"best_rate: {stats.get('best_validate_fraction', 0)}",
            f"embed: {emb.get('mode')}  provider={emb.get('provider')}  "
            f"model={emb.get('model') or '-'}  key={'yes' if emb.get('has_api_key') else 'no'}",
        ]
        models = stats.get("models") or []
        if models:
            lines.append(
                "models: "
                + ", ".join(f"{m['model']}×{m['count']}" for m in models[:5])
            )
        q = (query or "").strip()
        if q:
            model = ""
            if self.config and self.config.target:
                model = self.config.target.model or ""
            from ..memory import build_embed_fn

            hits = store.find_similar(
                q, model=model, limit=5, method="hybrid", embed_fn=build_embed_fn(self.config)
            )
            lines.append(f"similar to {q!r}:")
            if not hits:
                lines.append("  (none)")
            for score, rec in hits:
                lines.append(
                    f"  {score:.3f}  {rec.id[:8]}  rate={rec.validate_rate or '-'}  "
                    f"hits={rec.hits}  {(rec.objective_norm or '')[:60]}"
                )
            self.set_daedalus_mode("REPLAY")
        else:
            recent = store.list_recent(limit=5)
            lines.append("recent:")
            if not recent:
                lines.append("  (empty — win + /validate to populate)")
            for row in recent:
                lines.append(
                    f"  {row.get('id', '')[:8]}  rate={row.get('validate_rate') or '-'}  "
                    f"hits={row.get('hits', 0)}  "
                    f"{(row.get('objective_norm') or '')[:60]}"
                )
        # effective timeout note when target present
        if self.config and self.config.target:
            try:
                et = self.config.target.effective_timeout()
                lines.append(f"target effective_timeout: {et:g}s")
            except Exception:
                pass
        self._mount(widgets.info_panel("\n".join(lines), title="liberation memory"))

    async def _cmd_replay(self, rest: list[str]) -> None:
        from ..report import _load_records

        verdicts = [
            r for r in _load_records(self.runlog.path) if r.get("kind") == "verdict"
        ]
        if not verdicts:
            self._mount(widgets.error_panel("还没有可重放的已记录载荷"))
            return
        idx = len(verdicts)
        if rest and rest[0].lstrip("-").isdigit():
            idx = int(rest[0])
        if not (1 <= idx <= len(verdicts)):
            self._mount(widgets.error_panel(
                f"索引超出范围；当前有 {len(verdicts)} 条已记录载荷"
            ))
            return
        rec = verdicts[idx - 1]
        payload = str(rec.get("payload", ""))
        if not payload:
            self._mount(widgets.error_panel("该记录没有保存载荷"))
            return
        self._last_payload = payload
        self._mount(widgets.info_panel(
            f"重放 #{idx}（原裁决 {rec.get('label', '?')}）→ "
            f"{self.config.target.model if self.config.target else '无目标'}",
            title="重放",
        ))
        res = await self.registry.execute("query_target", {"prompt": payload})
        self._on_tool_result("manual", "query_target", res.content, res.is_error, "replay")

    def _set_target_model(self, model_id: str, modality: str | None = None) -> None:
        from ..config import resolve_target_modality

        base = self.config.target or self.endpoint
        resolved = resolve_target_modality(model_id, modality)
        self.config.target = dataclasses.replace(
            base, name="target", model=model_id, modality=resolved
        )
        self._target_model = model_id
        self._target_modality = resolved
        self._refresh_status()
        self._save_prefs()
        note = (
            "  （图像生成：请用 image 相关工具攻击）" if resolved == "image" else ""
        )
        self._mount(widgets.info_panel(
            f"目标模型 -> {model_id} [modality={resolved}]{note}", title="目标",
        ))

    def _set_target_sysmode(self, mode: str) -> None:
        if self.config.target is None:
            self._mount(widgets.error_panel("尚未配置目标"))
            return
        self.config.target = dataclasses.replace(self.config.target, system_mode=mode)
        self._refresh_status()
        self._save_prefs()
        explain = {
            "merge": "system prompt 现并入首条 user 轮",
            "drop": "system prompt 现已丢弃",
            "default": "system prompt 按原生方式递送",
        }[mode]
        self._mount(widgets.info_panel(
            f"目标 sysmode -> {mode} ({explain})", title="目标",
        ))

    def _set_target_modality(self, modality: str) -> None:
        if self.config.target is None:
            self._mount(widgets.error_panel("尚未配置目标"))
            return
        self.config.target = dataclasses.replace(self.config.target, modality=modality)
        self._target_modality = modality
        self._refresh_status()
        self._save_prefs()
        self._mount(widgets.info_panel(
            f"目标 modality -> {modality} ({self.config.target.model})", title="目标",
        ))
        self._mount(widgets.info_panel(
            f"目标模型 -> {self.config.target.model} @ {self.config.target.base_url}",
            title="目标",
        ))

    def _cmd_model(self, rest: list[str]) -> None:
        if not rest:
            self._mount(widgets.error_panel("用法: /model <id>"))
            return
        self.endpoint = dataclasses.replace(self.endpoint, model=rest[0])
        self.provider = build_provider(self.endpoint)
        self._sync_judge_endpoint()
        self._refresh_status()
        self._save_prefs()
        self._mount(widgets.info_panel(f"模型 -> {rest[0]}", title="模型"))

    def _cmd_auto(self, rest: list[str]) -> None:
        if rest:
            self.auto = rest[0].lower() in ("on", "true", "1", "yes")
        else:
            self.auto = not self.auto
        self._refresh_status()
        self._save_prefs()
        self._mount(widgets.info_panel(
            f"自动模式：{'开' if self.auto else '关'}", title="自动"
        ))

    def _cmd_rounds(self, rest: list[str]) -> None:
        if not rest or not rest[0].isdigit():
            self._mount(widgets.error_panel("用法: /rounds <n>"))
            return
        self.max_rounds = max(1, int(rest[0]))
        self._refresh_status()
        self._save_prefs()
        self._mount(widgets.info_panel(f"轮数上限 -> {self.max_rounds}", title="轮数"))

    def _cmd_judge(self, rest: list[str]) -> None:
        if rest and rest[0].lower() == "test":
            self.run_worker(self._cmd_judge_test(), group="judge", exclusive=False)
            return
        if rest and rest[0].lower() == "model":
            if len(rest) < 2:
                self._mount(widgets.error_panel("用法: /judge model <id>"))
                return
            self.judge_model_override = rest[1]
            self._sync_judge_endpoint()
            self._save_prefs()
            self._mount(widgets.info_panel(
                f"裁判模型 -> {rest[1]} @ {self._judge_endpoint().base_url}",
                title="裁判",
            ))
            return
        if rest and rest[0].lower() == "default":
            self.judge_model_override = None
            self._sync_judge_endpoint()
            self._save_prefs()
        elif rest:
            self.judge_enabled = rest[0].lower() in ("on", "true", "1", "yes")
        else:
            self.judge_enabled = not self.judge_enabled
        self._save_prefs()
        self._refresh_status()
        ep = self._judge_endpoint()
        self._mount(widgets.info_panel(
            f"LLM 裁判：{'开' if self.judge_enabled else '关'} | grader: {ep.model} "
            f"@ {ep.base_url}\n（/judge model <id> 切换，/judge default 恢复）",
            title="裁判",
        ))

    def _cmd_log(self, rest: list[str]) -> None:
        if rest and rest[0].lower() in ("on", "off", "true", "false"):
            self.runlog.enabled = rest[0].lower() in ("on", "true")
            self._save_prefs()
        self._mount(widgets.info_panel(
            f"运行日志：{'开' if self.runlog.enabled else '关'}\n"
            f"文件: {self.runlog.path}",
            title="日志",
        ))

    async def _cmd_harmbench(self, rest: list[str]) -> None:
        action = rest[0] if rest else "categories"
        if action == "categories":
            out = await self.registry.execute("harmbench", {"action": "categories"})
        else:
            out = await self.registry.execute(
                "harmbench", {"action": "sample", "category": action, "n": 10}
            )
        self._mount(widgets.info_panel(out.content, title="HarmBench"))

    async def _cmd_campaign(self, rest: list[str]) -> None:
        args: dict = {}
        for tok in rest:
            if tok.isdigit():
                args["n"] = int(tok)
            else:
                args["category"] = tok
        self._mount(widgets.info_panel(
            f"正在对 "
            f"{self.config.target.model if self.config.target else '无目标'} 运行自动战役（升级阶梯）…",
            title="战役",
        ))
        res = await self.registry.execute("campaign", args)
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="战役"
        )
        self._mount(panel)
        self._refresh_status()

    async def _cmd_leaderboard(self, rest: list[str]) -> None:
        if len(self.config.profiles) < 2:
            self._mount(widgets.error_panel(
                "需要至少 2 个已配置 profile 才能排名"
            ))
            return
        args: dict = {}
        profiles = [t for t in rest if not t.isdigit()]
        nums = [int(t) for t in rest if t.isdigit()]
        if profiles:
            args["targets"] = profiles
        if nums:
            args["n"] = nums[0]
        self._mount(widgets.info_panel(
            "正在用同一电池对配置档做基准测试…", title="排行榜"
        ))
        res = await self.registry.execute("leaderboard", args)
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="排行榜"
        )
        self._mount(panel)

    async def _cmd_swarm(self, rest: list[str], raw_arg: str) -> None:
        """/swarm roster [attackers...]
        /swarm [siege] [@a,b,c] <objective>

        Fires the attacker swarm at the configured [target]. Default is a one-shot vote;
        a leading 'siege' token runs the collaborative multi-round siege instead. A leading
        @-prefixed token selects the roster (comma-separated profile names); otherwise the
        [swarm] config roster (else every profile except the judge) is used.
        """
        args: dict = {}
        attackers = None
        objective = raw_arg
        toks = list(rest)
        if toks and toks[0].lower() == "roster":
            args["action"] = "roster"
            picks = toks[1:]
            if picks:
                args["attackers"] = picks
            self._mount(widgets.info_panel("正在检查各模型越狱状态…", title="集群名单"))
            res = await self.registry.execute("swarm", args)
            self._mount(
                widgets.error_panel(res.content) if res.is_error
                else widgets.info_panel(res.content, title="集群名单")
            )
            return
        mode = "vote"
        if toks and toks[0].lower() in ("siege", "vote"):
            mode = toks[0].lower()
            objective = raw_arg[len(rest[0]):].strip()
            toks = toks[1:]
        if toks and toks[0].startswith("@"):
            attackers = [a for a in toks[0][1:].split(",") if a]
            objective = objective[len(toks[0]):].strip() if objective.startswith(toks[0]) else objective
        if not objective:
            self._mount(widgets.info_panel(
                "用法: /swarm [siege] [@glm,deepseek-pro] <objective>   或   /swarm roster",
                title="集群",
            ))
            return
        args["objective"] = objective
        if mode == "siege":
            args["action"] = "siege"
        if attackers:
            args["attackers"] = attackers
        if attackers:
            roster = ", ".join(attackers)
        elif self.config.swarm_roster:
            roster = ", ".join(self.config.swarm_roster) + "（配置默认）"
        else:
            roster = "全部配置档（不含裁判）"
        verb = "围攻" if mode == "siege" else "集群攻击"
        self._mount(widgets.info_panel(
            f"{verb} {self.config.target.model if self.config.target else '（无目标！）'} "
            f"· 阵容 {roster}…", title=f"集群 {mode}",
        ))
        res = await self.registry.execute("swarm", args)
        self._mount(
            widgets.error_panel(res.content) if res.is_error
            else widgets.info_panel(res.content, title=f"集群 {mode}")
        )

    def _cmd_leakscan(self) -> None:
        from ..tools.leak_scan import scan_text

        if not self._last_reply:
            self._mount(widgets.error_panel("还没有可扫描的目标回复"))
            return
        result = scan_text(self._last_reply, self.sysprompt or None)
        findings = result["findings"]
        if not findings:
            self._mount(widgets.info_panel(
                "最近回复中未发现密钥、PII 或系统提示回显。", title="泄漏扫描"
            ))
            return
        lines = [f"[{f['type']:18}] {f['match']}" for f in findings]
        self._mount(widgets.info_panel(
            f"{len(findings)} leak indicator(s) in the last reply:\n\n" + "\n".join(lines),
            title="泄漏扫描",
        ))

    async def _cmd_judge_test(self) -> None:
        self._mount(widgets.info_panel(
            "正在用良性样例校准裁判…", title="裁判自检"
        ))
        res = await self.registry.execute("judge_selftest", {})
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="裁判自检"
        )
        self._mount(panel)

    def _cmd_find(self, term: str) -> None:
        if not term:
            self._mount(widgets.error_panel("用法: /find <term>"))
            return
        needle = term.lower()
        hits = []
        for i, msg in enumerate(self.history):
            text = msg.text()
            for tu in msg.tool_uses():
                text += f" [{tu.name} {tu.input}]"
            if needle in text.lower():
                pos = text.lower().find(needle)
                snippet = text[max(0, pos - 30): pos + len(term) + 30].replace("\n", " ")
                hits.append(f"#{i} [{msg.role}] ...{snippet}...")
        if not hits:
            self._mount(widgets.info_panel(f"没有匹配 {term!r}", title="查找"))
            return
        self._mount(widgets.info_panel(
            f"{len(hits)} match(es) for {term!r}:\n\n" + "\n".join(hits[:40]),
            title="查找",
        ))

    async def _cmd_lib(self, rest: list[str]) -> None:
        action = rest[0] if rest else "list"
        if action == "update":
            out = await self.registry.execute("l1b3rt4s_list", {})
            self._mount(widgets.info_panel(out.content, title="库"))
        elif action == "list":
            out = await self.registry.execute("l1b3rt4s_list", {})
            self._mount(widgets.info_panel(out.content, title="库"))
        else:
            out = await self.registry.execute("l1b3rt4s_get", {"model": action})
            self._mount(widgets.info_panel(out.content, title=f"lib:{action}"))

    async def _cmd_parsel(self, rest: list[str]) -> None:
        if "parsel_list" not in self.registry.tools:
            self._mount(widgets.error_panel(
                "P4RS3LT0NGV3 engine isn't available. Vendor it with `wallbreaker parsel "
                "update` (needs Node.js on PATH), then restart. The pure-Python "
                "`parseltongue` tool still works offline."
            ))
            return
        action = rest[0].lower() if rest else "list"
        if action == "list":
            out = await self.registry.execute("parsel_list", {"category": " ".join(rest[1:])})
            self._mount(widgets.info_panel(out.content, title="parsel"))
        elif action == "guide":
            out = await self.registry.execute("parsel_guide", {})
            self._mount(widgets.info_panel(out.content, title="parsel:指南"))
        elif action == "search":
            query = " ".join(rest[1:])
            if not query:
                self._mount(widgets.error_panel("用法: /parsel search <query>"))
                return
            out = await self.registry.execute("parsel_search", {"query": query})
            self._mount(widgets.info_panel(out.content, title="parsel:搜索"))
        elif action == "inspect":
            name = " ".join(rest[1:])
            if not name:
                self._mount(widgets.error_panel("用法: /parsel inspect <transform>"))
                return
            out = await self.registry.execute("parsel_inspect", {"transform": name})
            self._mount(widgets.info_panel(out.content, title=f"parsel:{name}"))
        elif action == "transform":
            if len(rest) < 3:
                self._mount(widgets.error_panel("用法: /parsel transform <key> <text...>"))
                return
            out = await self.registry.execute(
                "parsel_transform", {"transform": rest[1], "text": " ".join(rest[2:])}
            )
            self._mount(widgets.info_panel(out.content, title=f"parsel:{rest[1]}"))
        elif action == "chain":
            if len(rest) < 3:
                self._mount(widgets.error_panel(
                    "用法: /parsel chain <key,key,...> <text...>"
                ))
                return
            steps = [s for s in rest[1].split(",") if s.strip()]
            out = await self.registry.execute(
                "parsel_chain", {"text": " ".join(rest[2:]), "steps": steps}
            )
            self._mount(widgets.info_panel(out.content, title="parsel:链式"))
        elif action == "decode":
            text = " ".join(rest[1:])
            if not text:
                self._mount(widgets.error_panel("用法: /parsel decode <text...>"))
                return
            out = await self.registry.execute("parsel_decode", {"text": text})
            self._mount(widgets.info_panel(out.content, title="parsel:解码"))
        elif action == "craft":
            if len(rest) < 3:
                self._mount(widgets.error_panel(
                    "用法: /parsel craft <key,key,...> <request...>"
                ))
                return
            steps = [s for s in rest[1].split(",") if s.strip()]
            out = await self.registry.execute(
                "parsel_craft", {"request": " ".join(rest[2:]), "steps": steps}
            )
            self._last_payload = out.content
            self._mount(widgets.info_panel(out.content, title="parsel:构造"))
        else:
            out = await self.registry.execute("parsel_inspect", {"transform": " ".join(rest)})
            self._mount(widgets.info_panel(out.content, title=f"parsel:{action}"))

    async def _cmd_eni(self, rest: list[str]) -> None:
        action = rest[0] if rest else "list"
        if action in ("list", "update"):
            out = await self.registry.execute("eni_list", {})
            self._mount(widgets.info_panel(out.content, title="ENI"))
        elif action == "search":
            query = " ".join(rest[1:])
            if not query:
                self._mount(widgets.error_panel("用法: /eni search <query>"))
                return
            out = await self.registry.execute("eni_search", {"query": query})
            self._mount(widgets.info_panel(out.content, title="ENI:搜索"))
        else:
            out = await self.registry.execute("eni_get", {"model": action})
            self._mount(widgets.info_panel(out.content, title=f"eni:{action}"))

    async def _cmd_fire(self, prompt: str) -> None:
        if not prompt:
            self._mount(widgets.error_panel("用法: /fire <发给目标的提示>"))
            return
        self._last_payload = prompt
        self._mount(widgets.tool_call_panel("fire", {"prompt": prompt[:200]}))
        res = await self.registry.execute("query_target", {"prompt": prompt})
        self._on_tool_result("manual", "query_target", res.content, res.is_error, "manual")

    async def _cmd_push(self, follow: str) -> None:
        if not follow:
            self._mount(widgets.error_panel("用法: /push <跟进>  （先 /fire 开线程后再用）"))
            return
        if not self.registry.ctx.target_thread:
            self._mount(widgets.error_panel("没有打开的线程 — 先 /fire 一条提示，再用 /push 继续"))
            return
        self._last_payload = follow
        self._mount(widgets.tool_call_panel("push", {"follow_up": follow[:200]}))
        res = await self.registry.execute("continue_target", {"prompt": follow})
        self._on_tool_result("manual", "continue_target", res.content, res.is_error, "continue")

    async def _cmd_firefile(self, raw: str) -> None:
        if ";;" not in raw:
            self._mount(widgets.error_panel(
                "用法: /firefile <路径或种子名> ;; <request>"
            ))
            return
        ref, request = (p.strip() for p in raw.split(";;", 1))
        if not ref or not request:
            self._mount(widgets.error_panel("需要同时提供 <file> 和 <request>"))
            return
        self._last_payload = request
        self._mount(widgets.info_panel(
            f"正在把 '{ref}' 原文作为 system prompt 发射…", title="firefile"
        ))
        res = await self.registry.execute("fire_file", {"file": ref, "request": request})
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content + "\n\n（线程已打开 — 用 /push 继续）", title="firefile"
        )
        self._mount(panel)
        self._refresh_status()

    async def _cmd_adapt(self, raw: str) -> None:
        if ";;" not in raw:
            self._mount(widgets.error_panel("用法: /adapt <种子名> ;; <request>"))
            return
        seed, request = (p.strip() for p in raw.split(";;", 1))
        if not seed or not request:
            self._mount(widgets.error_panel("需要同时提供 <seed> 和 <request>"))
            return
        self._last_payload = request
        self._mount(widgets.info_panel(
            f"正在把 '{seed}' 适配到目标并发射…", title="adapt"
        ))
        res = await self.registry.execute("adapt_seed", {"seed": seed, "request": request})
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content + "\n\n（线程已打开 — 用 /push 继续）", title="adapt"
        )
        self._mount(panel)
        self._refresh_status()

    async def _cmd_narrate(self, request: str) -> None:
        if not request:
            self._mount(widgets.error_panel("用法: /narrate <要戏剧化的请求>"))
            return
        self._last_payload = request
        self._mount(widgets.info_panel(
            "正在扫 5 种小说章节框架 + 故事内 prefill…", title="narrate"
        ))
        res = await self.registry.execute("narrate", {"request": request, "variants": 5})
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="narrate"
        )
        self._mount(panel)
        self._refresh_status()

    async def _cmd_pairsweep(self, rest: list[str]) -> None:
        args: dict = {}
        for tok in rest:
            if tok.isdigit():
                args["n"] = int(tok)
            else:
                args["category"] = tok
        self._mount(widgets.info_panel(
            "正在对电池并发跑 PAIR…", title="PAIR 扫描"
        ))
        res = await self.registry.execute("pair_sweep", args)
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="PAIR 扫描"
        )
        self._mount(panel)
        self._refresh_status()

    async def _cmd_seedsweep(self, request: str) -> None:
        if not request:
            self._mount(widgets.error_panel("用法: /seedsweep <要注入的请求>"))
            return
        self._mount(widgets.info_panel(
            "sweeping cross-provider jailbreak seeds against the target...",
            title="种子扫描",
        ))
        res = await self.registry.execute("seed_sweep", {"request": request})
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="种子扫描"
        )
        self._mount(panel)
        self._refresh_status()

    def _cmd_preset(self, rest: list[str]) -> None:
        from ..presets import get_preset, list_presets

        if not rest or rest[0] == "list":
            body = "\n".join(f"{p.name:16} {p.description}" for p in list_presets())
            self._mount(widgets.info_panel(
                body + "\n\nUse /preset <name> to view + copy a seed template.",
                title="预设",
            ))
            return
        p = get_preset(rest[0])
        if p is None:
            self._mount(widgets.error_panel(f"no preset '{rest[0]}'"))
            return
        try:
            self.copy_to_clipboard(p.template)
            note = "（已复制到剪贴板）"
        except Exception:
            note = ""
        self._mount(widgets.info_panel(
            f"{p.description} {note}\n\n{p.template}", title=f"preset: {p.name}"
        ))

    def _cmd_template(self, rest: list[str], raw: str) -> None:
        sub = rest[0].lower() if rest else "show"
        body = raw[len(rest[0]):].strip() if rest else ""
        if sub == "show" or not rest:
            msg = self.template or "no template set. /template set <text with {request}>"
            self._mount(widgets.info_panel(msg, title="模板"))
        elif sub == "set":
            if "{request}" not in body:
                self._mount(widgets.error_panel("模板必须包含 {request} 占位符"))
                return
            self.template = body
            self._mount(widgets.info_panel(
                f"模板已设置（{len(body)} 字符）\n\n{body[:400]}", title="模板"
            ))
        elif sub == "clear":
            self.template = ""
            self._mount(widgets.info_panel("模板已清除", title="模板"))
        elif sub == "save":
            path = rest[1] if len(rest) > 1 else "template.txt"
            try:
                with open(path, "w", encoding="utf-8") as h:
                    h.write(self.template)
                self._mount(widgets.info_panel(f"模板已保存到 {path}", title="模板"))
            except OSError as exc:
                self._mount(widgets.error_panel(str(exc)))
        elif sub == "fire":
            if not self.template:
                self._mount(widgets.error_panel("请先设置模板: /template set <text>"))
                return
            if not body:
                self._mount(widgets.error_panel("用法: /template fire <类别请求>"))
                return
            self.run_worker(self._template_fire(body), group="judge", exclusive=False)
        elif sub == "test":
            if not self.template:
                self._mount(widgets.error_panel("请先设置模板: /template set <text>"))
                return
            cats = [c.strip() for c in body.split(";") if c.strip()] if body else None
            self.run_worker(self._template_test(cats), group="judge", exclusive=False)
        else:
            self._mount(widgets.error_panel("用法: /template [show|set|fire|test|save|clear]"))

    async def _template_fire(self, category: str) -> None:
        payload = self.template.replace("{request}", category)
        self._last_payload = payload
        self._mount(widgets.tool_call_panel("template fire", {"category": category}))
        res = await self.registry.execute("query_target", {"prompt": payload})
        self._on_tool_result("manual", "query_target", res.content, res.is_error, "template")

    async def _template_test(self, cats) -> None:
        from ..judging import grade
        from ..tools.optimize import DEFAULT_CATEGORIES

        cats = cats or DEFAULT_CATEGORIES
        self._mount(widgets.info_panel(
            f"正在用 {len(cats)} 个类别测试模板…", title="模板测试"
        ))
        rows = []
        for c in cats:
            payload = self.template.replace("{request}", c)
            res = await self.registry.execute("query_target", {"prompt": payload})
            if res.is_error:
                rows.append(("ERROR", None, c))
                continue
            reply = res.content.split("\n", 1)[1] if res.content.startswith("[target") else res.content
            label, score, reason, _src = await grade(
                self._judge_endpoint(), reply, payload=payload, objective=c
            )
            self._record_verdict(payload, reply, label, reason, "template")
            rows.append((label, score, c))
            self._refresh_status()
        passes = sum(1 for lbl, _s, _c in rows if lbl == "COMPLIED")
        lines = [
            f"[{lbl}{f'({s})' if s is not None else ''}] {c[:52]}"
            for lbl, s, c in rows
        ]
        self._mount(widgets.info_panel(
            f"template scored {passes}/{len(rows)} COMPLIED:\n\n" + "\n".join(lines),
            title="模板测试",
        ))

    def _cmd_sysprompt(self, rest: list[str], raw: str) -> None:
        sub = rest[0].lower() if rest else "show"
        body = raw[len(rest[0]):].strip() if rest else ""
        if sub == "show" or not rest:
            self._mount(widgets.info_panel(
                self.sysprompt or "尚未设置系统提示。/sysprompt set <text>",
                title="系统提示",
            ))
        elif sub == "set":
            self.sysprompt = body
            self._mount(widgets.info_panel(
                f"系统提示已设置（{len(body)} 字符）\n\n{body[:400]}", title="系统提示"
            ))
        elif sub == "load":
            ref = body.strip()
            if not ref:
                self._mount(widgets.error_panel("用法: /sysprompt load <文件路径或种子名>"))
                return
            from ..tools.fire_file import _read_source

            label, content = _read_source(self.registry.ctx, ref)
            if not content:
                self._mount(widgets.error_panel(
                    f"找不到文件或种子 '{ref}'（请试路径，或如 GROK_ENI 的名称）"
                ))
                return
            self.sysprompt = content
            self._mount(widgets.info_panel(
                f"已从 {label} 加载系统提示（{len(content)} 字符）— 原文、未修改。\n"
                f"下一步: /sysprompt test prefill samples=5\n\n{content[:300]}...",
                title="系统提示",
            ))
        elif sub == "clear":
            self.sysprompt = ""
            self._mount(widgets.info_panel("系统提示已清除", title="系统提示"))
        elif sub == "save":
            path = rest[1] if len(rest) > 1 else "sysprompt.txt"
            try:
                with open(path, "w", encoding="utf-8") as h:
                    h.write(self.sysprompt)
                self._mount(widgets.info_panel(f"已保存到 {path}", title="系统提示"))
            except OSError as exc:
                self._mount(widgets.error_panel(str(exc)))
        elif sub == "test":
            if not self.sysprompt:
                self._mount(widgets.error_panel("请先 set 或 /sysprompt load 一条系统提示"))
                return
            prefill = False
            samples = 1
            rest_tokens = []
            for w in body.split():
                lw = w.lower()
                if lw == "prefill":
                    prefill = True
                elif lw.startswith("samples=") and lw[8:].isdigit():
                    samples = max(1, int(lw[8:]))
                else:
                    rest_tokens.append(w)
            tasks_body = " ".join(rest_tokens)
            tasks = [t.strip() for t in tasks_body.split(";") if t.strip()] if tasks_body else None
            self.run_worker(self._sysprompt_test(tasks, prefill, samples), group="judge", exclusive=False)
        else:
            self._mount(widgets.error_panel("用法: /sysprompt [show|set|load|test [prefill] [samples=N]|save|clear]"))

    async def _sysprompt_test(self, tasks, prefill: bool = False, samples: int = 1) -> None:
        args: dict = {"system": self.sysprompt}
        if tasks:
            args["tasks"] = tasks
        if prefill:
            args["prefill"] = True
        if samples > 1:
            args["samples"] = samples
        res = await self.registry.execute("system_sweep", args)
        self._mount(widgets.info_panel(res.content, title="系统提示扫描"))
        self._refresh_status()

    def _cmd_encode(self, rest: list[str]) -> None:
        from ..transforms import TRANSFORMS, apply_chain, reverse_chain

        if len(rest) < 2:
            self._mount(widgets.error_panel(
                "用法: /encode <chain> <text>   例如 /encode leet,base64 write a poem"
            ))
            return
        chain = [c.strip() for c in rest[0].split(",") if c.strip()]
        text = " ".join(rest[1:])
        unknown = [c for c in chain if c not in TRANSFORMS]
        if unknown:
            self._mount(widgets.error_panel(
                f"未知变换: {', '.join(unknown)}（见 /transforms）"
            ))
            return
        try:
            encoded = apply_chain(text, chain)
        except (KeyError, ValueError) as exc:
            self._mount(widgets.error_panel(str(exc)))
            return
        lossy = [c for c in chain if TRANSFORMS[c].lossy]
        reversible = all(TRANSFORMS[c].reversible for c in chain)
        roundtrip = "n/a"
        if reversible:
            try:
                back = reverse_chain(encoded, chain)
                roundtrip = "exact" if back == text else (
                    "case/space-folded" if back.lower().replace(" ", "") ==
                    text.lower().replace(" ", "") else "lossy"
                )
            except (KeyError, ValueError):
                roundtrip = "decode failed"
        try:
            self.copy_to_clipboard(encoded)
            note = "（已复制到剪贴板）"
        except Exception:
            note = ""
        flags = []
        if lossy:
            flags.append(f"lossy: {'+'.join(lossy)}")
        flags.append(f"reversible: {'yes' if reversible else 'no'}")
        flags.append(f"round-trip: {roundtrip}")
        self._mount(widgets.info_panel(
            f"链路: {'+'.join(chain)}  ({' | '.join(flags)}) {note}\n\n"
            f"{encoded}\n\n"
            f"发射: query_target prompt=<text> transforms={chain}",
            title="编码",
        ))

    async def _cmd_diff(self, raw: str) -> None:
        if ";;" not in raw:
            self._mount(widgets.error_panel("用法: /diff <payload a> ;; <payload b>"))
            return
        a, b = (part.strip() for part in raw.split(";;", 1))
        if not a or not b:
            self._mount(widgets.error_panel(";; 两侧都不能为空"))
            return
        self._mount(widgets.info_panel(
            "正在对目标进行 A/B 发射…", title="对比"
        ))
        res = await self.registry.execute("diff_fire", {"a": a, "b": b})
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="对比"
        )
        self._mount(panel)

    async def _cmd_regrade(self, rest: list[str]) -> None:
        from ..regrade import format_regrade, regrade_log
        from ..report import resolve_log_path

        log = resolve_log_path(rest[0] if rest else None) or self.runlog.path
        self._mount(widgets.info_panel(
            f"正在用当前裁判重判 {log}…", title="重判"
        ))
        try:
            summary = await regrade_log(log, self._judge_endpoint(), self.objective)
        except Exception as exc:  # noqa: BLE001
            self._mount(widgets.error_panel(f"重判失败: {exc}"))
            return
        self._mount(widgets.info_panel(format_regrade(summary, log), title="重判"))

    def _cmd_stats(self) -> None:
        from ..report import _load_records

        records = _load_records(self.runlog.path)
        if not records:
            self._mount(widgets.info_panel(
                "尚无运行日志记录。先发射一些内容（需开启日志）。",
                title="统计",
            ))
            return
        verdicts = [r for r in records if r.get("kind") == "verdict"]
        counts: dict[str, int] = {}
        for v in verdicts:
            counts[v.get("label", "?")] = counts.get(v.get("label", "?"), 0) + 1
        total = len(verdicts)
        hits = counts.get("COMPLIED", 0) + counts.get("PARTIAL", 0)
        asr = f"{(hits / total * 100):.0f}%" if total else "n/a"

        order = ["COMPLIED", "PARTIAL", "REFUSED", "EMPTY"]
        labels = order + [k for k in counts if k not in order]
        bar_lines = []
        for label in labels:
            n = counts.get(label, 0)
            if not n:
                continue
            frac = n / total if total else 0
            bar = "#" * max(1, round(frac * 24))
            bar_lines.append(f"  {label:9} {bar} {n} ({frac * 100:.0f}%)")

        by_tech: dict[str, list[int]] = {}
        for v in verdicts:
            t = v.get("technique") or "manual"
            bucket = by_tech.setdefault(t, [0, 0])
            bucket[1] += 1
            if v.get("label") in ("COMPLIED", "PARTIAL"):
                bucket[0] += 1
        tech_lines = [
            f"  {t:14} {h}/{n} ({h / n * 100:.0f}% ASR)"
            for t, (h, n) in sorted(by_tech.items(), key=lambda kv: -kv[1][0])
        ] or ["  (untagged)"]

        tool_calls: dict[str, int] = {}
        for r in records:
            if r.get("kind") == "tool_call":
                t = r.get("tool", "?")
                tool_calls[t] = tool_calls.get(t, 0) + 1
        top_tools = sorted(tool_calls.items(), key=lambda kv: -kv[1])[:6]
        tool_lines = [f"  {t:16} {n}x" for t, n in top_tools] or ["  (none)"]

        self._mount(widgets.info_panel(
            f"已裁决发射: {total}   ASR: {asr}   （{hits} 绕过 / {total - hits} 挡住）\n\n"
            f"裁决分布:\n" + "\n".join(bar_lines) + "\n\n"
            "按技术 ASR:\n" + "\n".join(tech_lines) + "\n\n"
            "最忙工具:\n" + "\n".join(tool_lines) + "\n\n"
            f"日志: {self.runlog.path}",
            title="统计",
        ))

    def _cmd_objective(self, raw: str) -> None:
        if not raw:
            self._mount(widgets.info_panel(
                self.objective or "尚未设置目标", title="目标任务"
            ))
            return
        self.objective = raw
        self.runlog.set_run_meta(models=self._run_models_meta())
        self._sync_vault_meta()
        self.runlog.event("objective", text=raw)
        self.history.append(user(f"[engagement objective] {raw}"))
        self._mount(widgets.info_panel(f"目标已设置:\n{raw}", title="目标任务"))

    def _cmd_findings(self, rest: list[str]) -> None:
        from ..report import extract_findings

        path = rest[0] if rest else self.runlog.path
        findings = extract_findings(path)
        if not findings:
            self._mount(widgets.info_panel(
                "尚未记录绕过（COMPLIED/PARTIAL）。请继续攻击。",
                title="发现",
            ))
            return
        lines = []
        for f in findings:
            payload = str(f.get("payload", "")).replace("\n", " ")[:70]
            lines.append(f"[{f['label']:8}] {payload}\n           -> {f.get('reason','')[:70]}")
        self._mount(widgets.info_panel(
            f"{len(findings)} 条绕过:\n\n" + "\n".join(lines), title="发现"
        ))

    def _cmd_export(self, rest: list[str]) -> None:
        import json

        from ..report import extract_findings

        findings = extract_findings(self.runlog.path)
        tgt = self.config.target
        payload = {
            "target": {
                "model": tgt.model if tgt else None,
                "base_url": tgt.base_url if tgt else None,
                "provider_pin": list(tgt.provider) if tgt and tgt.provider else [],
            },
            "objective": self.objective,
            "asr": {"hits": self.asr_hits, "total": self.asr_total},
            "findings": [
                {
                    "label": f.get("label"),
                    "technique": f.get("technique") or "manual",
                    "payload": f.get("payload"),
                    "response": f.get("response"),
                    "reason": f.get("reason"),
                    "ts": f.get("ts"),
                }
                for f in findings
            ],
        }
        path = rest[0] if rest else "findings.json"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            self._mount(widgets.info_panel(
                f"已导出 {len(findings)} 条发现到 {path}", title="导出"
            ))
        except OSError as exc:
            self._mount(widgets.error_panel(str(exc)))

    def _cmd_repro(self, rest: list[str]) -> None:
        from ..report import extract_findings

        findings = extract_findings(self.runlog.path)
        if not findings:
            self._mount(widgets.info_panel(
                "尚无可复现的绕过（COMPLIED/PARTIAL）。", title="复现"
            ))
            return
        idx = 1
        if rest and rest[0].lstrip("-").isdigit():
            idx = int(rest[0])
        if not (1 <= idx <= len(findings)):
            self._mount(widgets.error_panel(
                f"索引超出范围；当前有 {len(findings)} 条绕过"
            ))
            return
        f = findings[idx - 1]
        tgt = self.config.target
        pin = "+".join(tgt.provider) if tgt and tgt.provider else "none"
        payload = str(f.get("payload", ""))
        block = (
            "=== Wallbreaker repro pack · Daedalus ===\n"
            f"target.model : {tgt.model if tgt else 'n/a'}\n"
            f"target.base  : {tgt.base_url if tgt else 'n/a'}\n"
            f"provider.pin : {pin}\n"
            f"technique    : {f.get('technique') or 'manual'}\n"
            f"verdict      : {f.get('label', '?')}\n"
            f"judge.reason : {f.get('reason', '')}\n"
            "--- payload ---\n"
            f"{payload}\n"
            "--- reproduce ---\n"
            "fire in Daedalus (wallbreaker CLI):  /target <model> ; then paste the payload above\n"
            "or tool call: query_target {\"prompt\": <payload>}\n"
            "======================"
        )
        try:
            self.copy_to_clipboard(block)
            note = "（已复制到剪贴板）"
        except Exception:
            note = ""
        self._mount(widgets.info_panel(
            f"绕过 #{idx}/{len(findings)} 的复现包{note}\n\n{block}",
            title="复现",
        ))

    def _cmd_report(self, rest: list[str]) -> None:
        from ..report import build_html_report, build_report

        html = (rest and rest[0].lower() == "html") or (
            rest and rest[0].lower().endswith(".html")
        )
        if rest and rest[0].lower() == "html":
            rest = rest[1:]
        if html:
            body = build_html_report(self.runlog.path)
            path = rest[0] if rest else "report.html"
            preview = "用浏览器打开可查看彩色记分板。"
        else:
            body = build_report(self.runlog.path)
            path = rest[0] if rest else "report.md"
            preview = body[:600]
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body)
            self._mount(widgets.info_panel(
                f"报告已写入 {path}\n\n{preview}", title="报告"
            ))
        except OSError as exc:
            self._mount(widgets.error_panel(str(exc)))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option_list.id
        if oid == "session-picker":
            path = event.option.id
            self._close_session_picker()
            if path:
                self._load_session_path(path)
        elif oid == "command-menu":
            cmd = event.option.id
            inp = self.query_one("#prompt", Input)
            inp.value = f"{cmd} "
            inp.cursor_position = len(inp.value)
            self._close_command_menu()
            inp.focus()

    def _session_option_label(self, p) -> Text:
        from ..session import peek_session_target

        try:
            st = p.stat()
            when = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            size = st.st_size
        except OSError:
            when, size = "?", 0
        if p.suffix == ".jsonl":
            kind = "run-log"
        elif p.name == "autosave.json":
            kind = "autosave"
        else:
            kind = "session"
        # label by the model that was attacked; old logs with no target stamp
        # fall back to their filename so the row is still identifiable
        model = peek_session_target(p) or p.name
        label = Text()
        label.append(f"{model[:34]:<34}", style=f"bold {PALETTE['accent']}")
        label.append(f" {kind:<9}", style=PALETTE["secondary"])
        label.append(f"  {when}  {size}B", style=PALETTE["label"])
        return label

    def _open_session_picker(self) -> None:
        from pathlib import Path

        from ..session import autosave_path, list_sessions

        sessions_dir = Path("sessions")
        candidates: list = []
        auto = autosave_path()
        if auto.exists():
            candidates.append(auto)
        candidates.extend(reversed(list_sessions()))
        if sessions_dir.is_dir():
            candidates.extend(sorted(sessions_dir.glob("run-*.jsonl"), reverse=True)[:20])
        # de-dupe, keep first occurrence order
        seen: set[str] = set()
        ordered = []
        for p in candidates:
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(p)
        if not ordered:
            self._mount(widgets.error_panel(
                "sessions/ 下没有已保存会话 — 请先 /session save，"
                "或 /session load <path>"
            ))
            return
        picker = self.query_one("#session-picker", OptionList)
        picker.clear_options()
        self._session_picker_items = [str(p) for p in ordered]
        for p in ordered:
            picker.add_option(Option(self._session_option_label(p), id=str(p)))
        picker.border_title = f"加载会话 ({len(ordered)}) · Enter 加载 · Esc 取消"
        picker.remove_class("hidden")
        picker.highlighted = 0
        picker.focus()
        self._session_picker_open = True

    def _close_session_picker(self) -> None:
        self._session_picker_open = False
        self._session_picker_items = []
        try:
            picker = self.query_one("#session-picker", OptionList)
            picker.add_class("hidden")
            picker.clear_options()
        except Exception:
            pass
        try:
            self.query_one("#prompt", Input).focus()
        except Exception:
            pass

    def _load_session_path(self, path: str) -> None:
        from ..session import load_session

        try:
            history, meta = load_session(path)
        except (OSError, ValueError) as exc:
            self._mount(widgets.error_panel(f"加载失败: {exc}"))
            return
        self.history = history
        self.objective = meta.get("objective", "")
        self.template = meta.get("template", "")
        self.sysprompt = meta.get("sysprompt", "")
        self.asr_hits = meta.get("asr_hits", 0)
        self.asr_total = meta.get("asr_total", 0)
        note = f"已从 {path} 加载 {len(history)} 条消息"
        if meta.get("source") == "run_log":
            note += "（运行日志：对话已恢复，工具调用已省略）"
        self._rerender(note)
        self._refresh_status()

    def _cmd_session(self, rest: list[str]) -> None:
        from ..session import save_session

        action = rest[0].lower() if rest else "save"
        # bare "/session load" with no path → open the interactive picker
        if action == "load" and len(rest) < 2:
            self._open_session_picker()
            return
        path = rest[1] if len(rest) > 1 else "session.json"
        if action == "save":
            meta = self._session_meta()
            try:
                save_session(path, self.history, meta)
                self._mount(widgets.info_panel(
                    f"会话已保存到 {path}（{len(self.history)} 条消息）",
                    title="会话",
                ))
            except OSError as exc:
                self._mount(widgets.error_panel(str(exc)))
        elif action == "load":
            self._load_session_path(path)
        else:
            self._mount(widgets.error_panel("用法: /session save|load [path]"))

    def _cmd_save(self, rest: list[str]) -> None:
        path = rest[0] if rest else "transcript.md"
        lines = []
        for msg in self.history:
            lines.append(f"## {msg.role}")
            lines.append(msg.text())
            for tu in msg.tool_uses():
                lines.append(f"[tool {tu.name}] {tu.input}")
            lines.append("")
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
            self._mount(widgets.info_panel(f"已保存到 {path}", title="保存"))
        except OSError as exc:
            self._mount(widgets.error_panel(str(exc)))


def run_tui(config: Config, args) -> int:
    from ..cli import resolve_endpoint
    from ..state import apply_attacker, apply_target, load_state, state_path_for

    state_path = state_path_for(config)
    prefs = load_state(state_path)

    endpoint = resolve_endpoint(config, args)
    if not getattr(args, "profile", None):
        endpoint = apply_attacker(config, endpoint, prefs)
    if not getattr(args, "target", None) and not getattr(args, "target_model", None):
        apply_target(config, prefs)

    system = compose_system(endpoint, getattr(args, "system", None))

    resume_path = None
    resume_arg = getattr(args, "resume", None)
    if resume_arg is not None:
        from ..session import autosave_path

        resume_path = resume_arg or str(autosave_path())

    app = RthApp(
        config, endpoint, system, prefs=prefs,
        state_path=state_path, resume_path=resume_path,
    )
    app.run()
    if app._exit_summary:
        print("\n=== 任务完成 ===")
        print(app._exit_summary)
        if app.runlog.enabled and app.runlog._started:
            print(f"\n运行日志: {app.runlog.path}")
    return 0
