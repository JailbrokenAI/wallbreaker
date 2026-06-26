from __future__ import annotations

import dataclasses

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Input, Static

from ..agent.loop import AgentEvents, run_autonomous, run_turn
from ..agent.messages import TextBlock, ToolResultBlock, user
from ..classify import classify, verdict_color
from ..config import Config, Endpoint
from ..prompts import DEFAULT_SYSTEM
from ..providers.factory import build_provider
from ..session import RunLog
from ..tools import build_registry
from ..transforms import list_transforms
from . import widgets

HELP_TEXT = """Slash commands:
/help                 show this help
/edit [new text]      rewind to your last message; prefill it to edit, or
                      pass new text to replace and resend it
/retry                regenerate the response to your last message
/undo                 remove your last message and its response
/profile [name]       show or switch the active profile
/target [name|model-id]   pick the model to attack (profile, or a raw model id)
/model <id>           override the active model id
/auto [on|off]        toggle autonomous loop (keeps attacking until done)
/autoexit [on|off]    when the agent calls finish(), close the tool (default on)
/rounds <n>           set the autonomous round cap
/transforms           list Parseltongue transforms
/preset [list|name]   curated jailbreak seed templates (copies to clipboard)
/objective [text]     set the engagement goal (threaded into the run + report)
/lib [list|update|MODEL]   browse the L1B3RT4S library
/log [on|off]         toggle the JSONL run log (every payload + verdict)
/judge [on|off]       LLM judge verdicts on target replies (default on)
/judge model <id>     swap the judge model live (/judge default to reset)
/asr                  show the attack scoreboard (hits / held / log path)
/findings [log]       list the bypasses (COMPLIED/PARTIAL) from the run log
/report [path]        write a markdown findings report from the run log
/session save|load [path]   persist or reload the whole engagement
/save [path]          save a plain-text transcript
/clear                clear the conversation
/quit                 exit

Ctrl+S report · Ctrl+Y copy last payload · Ctrl+L clear · Ctrl+C quit

Up / Down arrows recall your previous inputs into the prompt.
Type anything else to talk to the agent. It has shell, file, parseltongue,
l1b3rt4s, query_target, and http_request tools."""


class RthApp(App):
    CSS = """
    #log { padding: 0 1; }
    #status { height: 1; background: $boost; color: $text; padding: 0 1; }
    #status.busy { background: $warning; color: black; }
    #prompt { dock: bottom; }
    """
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
        ("ctrl+s", "report", "Report"),
        ("ctrl+y", "copy_payload", "Copy payload"),
    ]

    def __init__(
        self,
        config: Config,
        endpoint: Endpoint,
        system: str,
        prefs: dict | None = None,
        state_path=None,
    ) -> None:
        super().__init__()
        prefs = prefs or {}
        self.config = config
        self.endpoint = endpoint
        self.system = system
        self.provider = build_provider(endpoint)
        self.registry = build_registry(config)
        self.history = []
        self.max_tokens = 4096
        self.auto = bool(prefs.get("auto", True))
        self.max_rounds = int(prefs.get("rounds", 12))
        self._busy = False
        self._assistant: Static | None = None
        self._buf = ""
        self._input_history: list[str] = []
        self._hist_pos: int | None = None
        self.runlog = RunLog()
        self.runlog.enabled = bool(prefs.get("log", True))
        self.tokens_in = 0
        self.tokens_out = 0
        self.asr_hits = 0
        self.asr_total = 0
        self._last_payload = ""
        self.exit_on_finish = bool(prefs.get("exit_on_finish", True))
        self.judge_enabled = bool(prefs.get("judge", True))
        self.judge_model_override = prefs.get("judge_model")
        self._exit_summary: str | None = None
        self.objective = ""
        self._state_path = state_path
        self._target_profile = prefs.get("target_profile")
        self._target_model = prefs.get("target_model")

    def _save_prefs(self) -> None:
        if not self._state_path:
            return
        from ..state import save_state

        save_state(self._state_path, {
            "profile": self.endpoint.name,
            "attacker_model": self.endpoint.model,
            "target_profile": self._target_profile,
            "target_model": self._target_model,
            "auto": self.auto,
            "rounds": self.max_rounds,
            "exit_on_finish": self.exit_on_finish,
            "log": self.runlog.enabled,
            "judge": self.judge_enabled,
            "judge_model": self.judge_model_override,
        })

    def _judge_endpoint(self):
        base = self.config.judge or self.endpoint
        if self.judge_model_override:
            base = dataclasses.replace(base, name="judge", model=self.judge_model_override)
        return base

    def _sync_judge_endpoint(self) -> None:
        self.registry.ctx.judge_endpoint = self._judge_endpoint()

    def compose(self) -> ComposeResult:
        yield Static(self._status_text(), id="status")
        yield VerticalScroll(id="log")
        yield Input(placeholder="message, or /help", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._log = self.query_one("#log", VerticalScroll)
        self.registry.ctx.progress = self._tool_progress
        self._sync_judge_endpoint()
        self.query_one("#prompt", Input).focus()
        self._mount(widgets.info_panel(
            "rth red-team harness. /help for commands.", title="ready"
        ))

    def _tool_progress(self, message: str) -> None:
        self._mount(widgets.info_panel(message, title="progress"))

    def _status_text(self) -> str:
        tgt = self.config.target.model if self.config.target else "none"
        mode = f"auto({self.max_rounds})" if self.auto else "single"
        asr = (
            f"{self.asr_hits}/{self.asr_total}"
            if self.asr_total
            else "0/0"
        )
        state = "WORKING" if self._busy else "idle"
        tok = f"{self.tokens_in}>{self.tokens_out}tok"
        judge = "judge" if self.judge_enabled else "heur"
        return (
            f" {state} | profile={self.endpoint.name} | model={self.endpoint.model} | "
            f"target={tgt} | {mode} | ASR={asr}/{judge} | {tok}"
        )

    def _refresh_status(self) -> None:
        status = self.query_one("#status", Static)
        status.update(self._status_text())
        status.set_class(self._busy, "busy")

    def _mount(self, renderable) -> None:
        self._log.mount(Static(renderable))
        self._log.scroll_end(animate=False)

    def _ensure_assistant(self) -> None:
        if self._assistant is None:
            self._buf = ""
            self._assistant = Static(widgets.assistant_panel("", self.endpoint.model))
            self._log.mount(self._assistant)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
            return
        if self._busy:
            self._mount(widgets.error_panel("Agent is still working; wait for it."))
            return
        self._submit_user(text)

    def _submit_user(self, text: str) -> None:
        self._mount(widgets.user_panel(text))
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
        inp = self.query_one("#prompt", Input)
        if not inp.has_focus or not self._input_history:
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
            self._mount(widgets.error_panel("wait for the agent to finish"))
            return
        idxs = self._typed_user_indices()
        if not idxs:
            self._mount(widgets.error_panel("nothing to edit yet"))
            return
        i = idxs[-1]
        old = self.history[i].text()
        self.history = self.history[:i]
        self._rerender("rewound to your last message")
        if new_text:
            self._submit_user(new_text)
        else:
            inp = self.query_one("#prompt", Input)
            inp.value = old
            inp.cursor_position = len(old)
            inp.focus()

    def _cmd_retry(self) -> None:
        if self._busy:
            self._mount(widgets.error_panel("wait for the agent to finish"))
            return
        idxs = self._typed_user_indices()
        if not idxs:
            self._mount(widgets.error_panel("nothing to retry"))
            return
        self.history = self.history[: idxs[-1] + 1]
        self._rerender("retrying your last message")
        self._busy = True
        self.run_worker(self._agent_turn(), exclusive=True, group="agent")

    def _cmd_undo(self) -> None:
        if self._busy:
            self._mount(widgets.error_panel("wait for the agent to finish"))
            return
        idxs = self._typed_user_indices()
        if not idxs:
            self._mount(widgets.error_panel("nothing to undo"))
            return
        self.history = self.history[: idxs[-1]]
        self._rerender("removed your last exchange")

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
            self._mount(widgets.info_panel(note, title="edit"))

    async def _agent_turn(self) -> None:
        events = AgentEvents(
            on_text=self._on_text,
            on_tool_start=self._on_tool_start,
            on_tool_result=self._on_tool_result,
            on_turn_end=self._on_turn_end,
            on_error=self._on_error,
            on_round=self._on_round,
            on_usage=self._on_usage,
        )
        try:
            if self.auto:
                result = await run_autonomous(
                    self.provider,
                    self.registry,
                    self.history,
                    system=self.system,
                    events=events,
                    max_rounds=self.max_rounds,
                    max_tokens=self.max_tokens,
                )
                self._handle_auto_result(result)
            else:
                await run_turn(
                    self.provider,
                    self.registry,
                    self.history,
                    system=self.system,
                    events=events,
                    max_tokens=self.max_tokens,
                )
        finally:
            self._assistant = None
            self._busy = False
            self._refresh_status()

    def _on_usage(self, tin: int, tout: int) -> None:
        self.tokens_in += tin
        self.tokens_out += tout
        self._refresh_status()

    def _on_round(self, rnd: int, total: int) -> None:
        self._assistant = None
        self._mount(widgets.info_panel(f"round {rnd}/{total}", title="autonomous"))

    def _handle_auto_result(self, result) -> None:
        if result.status == "finished":
            summary = result.data.get("summary", "(no summary)")
            self._mount(widgets.info_panel(summary, title="engagement complete"))
            if self.exit_on_finish:
                self._exit_summary = summary
                self.exit()
                return
        elif result.status == "ask":
            self._mount(widgets.info_panel(
                result.data.get("question", "(no question)"),
                title="operator input needed",
            ))
        elif result.status == "stuck":
            self._mount(widgets.info_panel(
                result.data.get("question", "")
                or "Agent stalled twice with no action. Give it direction.",
                title="stalled, needs you",
            ))
        elif result.status == "max_rounds":
            self._mount(widgets.info_panel(
                f"hit round cap ({self.max_rounds}). Type to continue, "
                f"or raise it with /rounds <n>.",
                title="round cap",
            ))
        self.query_one("#prompt", Input).focus()

    def _on_text(self, delta: str) -> None:
        self._ensure_assistant()
        self._buf += delta
        assert self._assistant is not None
        self._assistant.update(widgets.assistant_panel(self._buf, self.endpoint.model))
        self._log.scroll_end(animate=False)

    def _on_turn_end(self, message) -> None:
        self._assistant = None
        self.runlog.assistant(message.text())

    def _on_tool_start(self, _id: str, name: str, args: dict) -> None:
        self._mount(widgets.tool_call_panel(name, args))
        self.runlog.tool_call(name, args)
        if name == "query_target":
            self._last_payload = str(args.get("prompt", ""))

    def _on_tool_result(self, _id: str, name: str, content: str, is_error: bool) -> None:
        self.runlog.tool_result(name, content, is_error)
        if name == "query_target" and not is_error:
            reply = content.split("\n", 1)[1] if content.startswith("[target") else content
            payload = self._last_payload
            if self.judge_enabled:
                self._mount(widgets.tool_result_panel(name, content, is_error))
                self.run_worker(
                    self._judge_and_post(payload, reply),
                    group="judge", exclusive=False,
                )
                return
            label, reason = classify(reply)
            self._record_verdict(payload, reply, label, reason)
            self._mount(widgets.tool_result_panel(
                name, content, is_error, (label, verdict_color(label))
            ))
            return
        self._mount(widgets.tool_result_panel(name, content, is_error))

    async def _judge_and_post(self, payload: str, reply: str) -> None:
        from ..judging import grade

        label, score, reason, source = await grade(
            self._judge_endpoint(), reply, payload=payload, objective=self.objective
        )
        self._record_verdict(payload, reply, label, reason)
        self._mount(widgets.verdict_panel(label, score, reason, source))
        self._refresh_status()

    def _record_verdict(self, payload: str, reply: str, label: str, reason: str) -> None:
        self.asr_total += 1
        if label in ("COMPLIED", "PARTIAL"):
            self.asr_hits += 1
        self.runlog.verdict(payload, reply, label, reason)

    def _on_error(self, message: str) -> None:
        self._mount(widgets.error_panel(message))

    def action_clear_log(self) -> None:
        self._clear()

    def action_report(self) -> None:
        self._cmd_report([])

    def action_copy_payload(self) -> None:
        if not self._last_payload:
            self._mount(widgets.info_panel("no payload fired yet", title="copy"))
            return
        try:
            self.copy_to_clipboard(self._last_payload)
            note = "last payload copied to clipboard"
        except Exception:
            note = f"clipboard unavailable; last payload:\n{self._last_payload[:500]}"
        self._mount(widgets.info_panel(note, title="copy"))

    def _clear(self) -> None:
        self.history = []
        self._log.remove_children()
        self._mount(widgets.info_panel("conversation cleared", title="ready"))

    def _handle_command(self, text: str) -> None:
        parts = text.split()
        cmd, rest = parts[0].lower(), parts[1:]
        raw_arg = text[len(parts[0]):].strip()
        if cmd in ("/quit", "/exit"):
            self.exit()
        elif cmd == "/help":
            self._mount(widgets.info_panel(HELP_TEXT, title="help"))
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
                f"exit-on-finish {'on' if self.exit_on_finish else 'off'}",
                title="autoexit",
            ))
        elif cmd == "/transforms":
            catalog = "\n".join(
                f"{t.name:14} {t.description}" for t in list_transforms()
            )
            self._mount(widgets.info_panel(catalog, title="transforms"))
        elif cmd == "/preset":
            self._cmd_preset(rest)
        elif cmd == "/lib":
            self.run_worker(self._cmd_lib(rest), exclusive=False)
        elif cmd == "/log":
            self._cmd_log(rest)
        elif cmd == "/judge":
            self._cmd_judge(rest)
        elif cmd == "/asr":
            self._mount(widgets.info_panel(
                f"targets hit: {self.asr_total}\n"
                f"complied/partial: {self.asr_hits}\n"
                f"guardrail held: {self.asr_total - self.asr_hits}\n"
                f"log: {self.runlog.path}",
                title="attack scoreboard",
            ))
        elif cmd == "/objective":
            self._cmd_objective(raw_arg)
        elif cmd == "/findings":
            self._cmd_findings(rest)
        elif cmd == "/report":
            self._cmd_report(rest)
        elif cmd == "/session":
            self._cmd_session(rest)
        elif cmd == "/save":
            self._cmd_save(rest)
        else:
            self._mount(widgets.error_panel(f"unknown command: {cmd}"))

    def _cmd_profile(self, rest: list[str]) -> None:
        if not rest:
            names = ", ".join(self.config.profiles)
            self._mount(widgets.info_panel(
                f"active: {self.endpoint.name}\navailable: {names}", title="profile"
            ))
            return
        name = rest[0]
        if name not in self.config.profiles:
            self._mount(widgets.error_panel(f"no profile '{name}'"))
            return
        self.endpoint = self.config.profiles[name]
        self.provider = build_provider(self.endpoint)
        self._sync_judge_endpoint()
        self._refresh_status()
        self._save_prefs()
        self._mount(widgets.info_panel(f"switched to {name}", title="profile"))

    def _cmd_target(self, rest: list[str]) -> None:
        if not rest:
            t = self.config.target
            avail = ", ".join(self.config.profiles)
            msg = (
                f"attacking: {t.model} @ {t.base_url}" if t else "no target configured"
            )
            self._mount(widgets.info_panel(
                f"{msg}\n\nset with:\n"
                f"  /target <profile>     use a profile's endpoint+model ({avail})\n"
                f"  /target model <id>    keep endpoint, swap the model id\n"
                f"  /target <model-id>    same, e.g. /target anthropic/claude-3.7-sonnet",
                title="target",
            ))
            return
        if rest[0].lower() == "model":
            if len(rest) < 2:
                self._mount(widgets.error_panel("usage: /target model <id>"))
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
                f"target set to profile '{name}': {src.model} @ {src.base_url}",
                title="target",
            ))
            return
        self._set_target_model(name)

    def _set_target_model(self, model_id: str) -> None:
        base = self.config.target or self.endpoint
        self.config.target = dataclasses.replace(base, name="target", model=model_id)
        self._target_model = model_id
        self._refresh_status()
        self._save_prefs()
        self._mount(widgets.info_panel(
            f"target model -> {model_id} @ {self.config.target.base_url}",
            title="target",
        ))

    def _cmd_model(self, rest: list[str]) -> None:
        if not rest:
            self._mount(widgets.error_panel("usage: /model <id>"))
            return
        self.endpoint = dataclasses.replace(self.endpoint, model=rest[0])
        self.provider = build_provider(self.endpoint)
        self._sync_judge_endpoint()
        self._refresh_status()
        self._save_prefs()
        self._mount(widgets.info_panel(f"model -> {rest[0]}", title="model"))

    def _cmd_auto(self, rest: list[str]) -> None:
        if rest:
            self.auto = rest[0].lower() in ("on", "true", "1", "yes")
        else:
            self.auto = not self.auto
        self._refresh_status()
        self._save_prefs()
        self._mount(widgets.info_panel(
            f"autonomous mode {'on' if self.auto else 'off'}", title="auto"
        ))

    def _cmd_rounds(self, rest: list[str]) -> None:
        if not rest or not rest[0].isdigit():
            self._mount(widgets.error_panel("usage: /rounds <n>"))
            return
        self.max_rounds = max(1, int(rest[0]))
        self._refresh_status()
        self._save_prefs()
        self._mount(widgets.info_panel(f"round cap -> {self.max_rounds}", title="rounds"))

    def _cmd_judge(self, rest: list[str]) -> None:
        if rest and rest[0].lower() == "model":
            if len(rest) < 2:
                self._mount(widgets.error_panel("usage: /judge model <id>"))
                return
            self.judge_model_override = rest[1]
            self._sync_judge_endpoint()
            self._save_prefs()
            self._mount(widgets.info_panel(
                f"judge model -> {rest[1]} @ {self._judge_endpoint().base_url}",
                title="judge",
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
            f"LLM judge {'on' if self.judge_enabled else 'off'} | grader: {ep.model} "
            f"@ {ep.base_url}\n(/judge model <id> to swap, /judge default to reset)",
            title="judge",
        ))

    def _cmd_log(self, rest: list[str]) -> None:
        if rest and rest[0].lower() in ("on", "off", "true", "false"):
            self.runlog.enabled = rest[0].lower() in ("on", "true")
            self._save_prefs()
        self._mount(widgets.info_panel(
            f"run logging {'on' if self.runlog.enabled else 'off'}\n"
            f"file: {self.runlog.path}",
            title="log",
        ))

    async def _cmd_lib(self, rest: list[str]) -> None:
        from ..tools import l1b3rt4s as lib

        action = rest[0] if rest else "list"
        if action == "update":
            out = await self.registry.execute("l1b3rt4s_list", {})
            self._mount(widgets.info_panel(out.content, title="lib"))
        elif action == "list":
            out = await self.registry.execute("l1b3rt4s_list", {})
            self._mount(widgets.info_panel(out.content, title="lib"))
        else:
            out = await self.registry.execute("l1b3rt4s_get", {"model": action})
            self._mount(widgets.info_panel(out.content, title=f"lib:{action}"))

    def _cmd_preset(self, rest: list[str]) -> None:
        from ..presets import get_preset, list_presets

        if not rest or rest[0] == "list":
            body = "\n".join(f"{p.name:16} {p.description}" for p in list_presets())
            self._mount(widgets.info_panel(
                body + "\n\nUse /preset <name> to view + copy a seed template.",
                title="presets",
            ))
            return
        p = get_preset(rest[0])
        if p is None:
            self._mount(widgets.error_panel(f"no preset '{rest[0]}'"))
            return
        try:
            self.copy_to_clipboard(p.template)
            note = "(copied to clipboard)"
        except Exception:
            note = ""
        self._mount(widgets.info_panel(
            f"{p.description} {note}\n\n{p.template}", title=f"preset: {p.name}"
        ))

    def _cmd_objective(self, raw: str) -> None:
        if not raw:
            self._mount(widgets.info_panel(
                self.objective or "no objective set", title="objective"
            ))
            return
        self.objective = raw
        self.runlog.event("objective", text=raw)
        self.history.append(user(f"[engagement objective] {raw}"))
        self._mount(widgets.info_panel(f"objective set:\n{raw}", title="objective"))

    def _cmd_findings(self, rest: list[str]) -> None:
        from ..report import extract_findings

        path = rest[0] if rest else self.runlog.path
        findings = extract_findings(path)
        if not findings:
            self._mount(widgets.info_panel(
                "no bypasses logged yet (COMPLIED/PARTIAL). Keep attacking.",
                title="findings",
            ))
            return
        lines = []
        for f in findings:
            payload = str(f.get("payload", "")).replace("\n", " ")[:70]
            lines.append(f"[{f['label']:8}] {payload}\n           -> {f.get('reason','')[:70]}")
        self._mount(widgets.info_panel(
            f"{len(findings)} bypass(es):\n\n" + "\n".join(lines), title="findings"
        ))

    def _cmd_report(self, rest: list[str]) -> None:
        from ..report import build_report

        markdown = build_report(self.runlog.path)
        path = rest[0] if rest else "report.md"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(markdown)
            self._mount(widgets.info_panel(
                f"report written to {path}\n\n{markdown[:600]}", title="report"
            ))
        except OSError as exc:
            self._mount(widgets.error_panel(str(exc)))

    def _cmd_session(self, rest: list[str]) -> None:
        from ..session import load_session, save_session

        action = rest[0].lower() if rest else "save"
        path = rest[1] if len(rest) > 1 else "session.json"
        if action == "save":
            meta = {
                "objective": self.objective,
                "asr_hits": self.asr_hits,
                "asr_total": self.asr_total,
                "profile": self.endpoint.name,
                "target_model": self.config.target.model if self.config.target else None,
            }
            try:
                save_session(path, self.history, meta)
                self._mount(widgets.info_panel(
                    f"session saved to {path} ({len(self.history)} messages)",
                    title="session",
                ))
            except OSError as exc:
                self._mount(widgets.error_panel(str(exc)))
        elif action == "load":
            try:
                history, meta = load_session(path)
            except (OSError, ValueError) as exc:
                self._mount(widgets.error_panel(f"load failed: {exc}"))
                return
            self.history = history
            self.objective = meta.get("objective", "")
            self.asr_hits = meta.get("asr_hits", 0)
            self.asr_total = meta.get("asr_total", 0)
            self._rerender(f"loaded {len(history)} messages from {path}")
            self._refresh_status()
        else:
            self._mount(widgets.error_panel("usage: /session save|load [path]"))

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
            self._mount(widgets.info_panel(f"saved to {path}", title="save"))
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

    system = getattr(args, "system", None) or DEFAULT_SYSTEM
    app = RthApp(config, endpoint, system, prefs=prefs, state_path=state_path)
    app.run()
    if app._exit_summary:
        print("\n=== engagement complete ===")
        print(app._exit_summary)
        if app.runlog.enabled and app.runlog._started:
            print(f"\nrun log: {app.runlog.path}")
    return 0
