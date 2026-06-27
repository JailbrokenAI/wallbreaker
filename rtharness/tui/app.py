from __future__ import annotations

import dataclasses
import difflib
import shlex

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
/help [topic]         show this help, or only lines matching a topic
/edit [new text]      rewind to your last message; prefill it to edit, or
                      pass new text to replace and resend it
/retry                regenerate the response to your last message
/undo                 remove your last message and its response
/profile [name]       show or switch the active profile
/target [name|model-id]   pick the model to attack (profile, or a raw model id)
/provider [name|none]     pin the OpenRouter backend for reproducible results
/validate [task]          re-fire 8x for the real success rate (validates last fire or a task)
/replay [n]               re-fire a logged payload (Nth, or last) at the CURRENT target + re-judge
/model <id>           override the active model id
/auto [on|off]        toggle autonomous loop (keeps attacking until done)
/autoexit [on|off]    when the agent calls finish(), close the tool (default on)
/rounds <n>           set the autonomous round cap
/transforms [filter]  list Parseltongue transforms (optional substring filter)
/encode <chain> <text>    preview a transform chain on text (no fire), copies result
/diff <a> ;; <b>          fire two payloads at the target and compare verdicts (A/B)
/tools [filter]        list the agent's tools (optional substring filter)
/preset [list|name]   curated jailbreak seed templates (copies to clipboard)
/objective [text]     set the engagement goal (threaded into the run + report)
/template set <text>  hold a working template ({request} placeholder) to hand-iterate
/template fire <cat>  fill {request}=<cat>, fire at target, auto-judge (set/save/clear too)
/template test [a;b]  fire the template across a category battery, scoreboard
/sysprompt set <text> hold ONE fixed system prompt; /sysprompt test [prefill] sweeps tasks
/lib [list|update|MODEL]   browse the L1B3RT4S library
/eni [list|search q|MODEL] browse the ENI persona-jailbreak collection
/seedsweep <request>       fire one request through many ENI+L1B3RT4S seeds, rank bypasses
/narrate <request>         wrap the ask as a novel chapter + in-story prefill, fire + judge
/harmbench [category]      standardized HarmBench behavior prompts (unbiased battery)
/campaign [category] [n]   auto-escalate a battery up the technique ladder, coverage matrix
/leaderboard [profiles..]  rank profiles by ASR on one battery (robustness benchmark)
/find <term>               search the conversation transcript for a term
/leakscan                  scan the last target reply for secrets/PII/system-prompt echo
/log [on|off]         toggle the JSONL run log (every payload + verdict)
/judge [on|off]       LLM judge verdicts on target replies (default on)
/judge model <id>     swap the judge model live (/judge default to reset)
/judge test           calibrate the grader on benign fixtures before trusting ASR
/asr                  show the attack scoreboard (hits / held / log path)
/stats                analytics from the run log: verdict mix, ASR bar, top tools
/findings [log]       list the bypasses (COMPLIED/PARTIAL) from the run log
/export [path]        dump structured findings as JSON (CI / downstream tooling)
/repro [n]            emit a copy-paste repro pack for the Nth bypass (or latest)
/report [html] [path] write a findings report (markdown, or html for a styled scoreboard)
/session save|load [path]   persist or reload the whole engagement
                      (the session also autosaves each turn; relaunch with rth --resume)
/save [path]          save a plain-text transcript
/clear                clear the conversation
/quit                 exit

Ctrl+S report · Ctrl+Y copy payload · Ctrl+T stats · Ctrl+R repro · Ctrl+L clear · Ctrl+C quit

Up / Down arrows recall your previous inputs into the prompt.
Type anything else to talk to the agent. It has shell, file, parseltongue,
l1b3rt4s, query_target, and http_request tools."""


KNOWN_COMMANDS = (
    "/help", "/edit", "/retry", "/regen", "/undo", "/clear", "/profile", "/target",
    "/provider", "/validate", "/replay", "/model", "/auto", "/autoexit", "/rounds",
    "/transforms", "/encode", "/diff", "/tools", "/preset", "/lib", "/eni", "/harmbench",
    "/campaign", "/leaderboard", "/seedsweep", "/narrate", "/find", "/leakscan", "/log",
    "/judge", "/asr", "/stats",
    "/objective", "/template", "/sysprompt", "/findings", "/export", "/repro",
    "/report", "/session", "/save", "/quit", "/exit",
)


def suggest_command(cmd: str, known=KNOWN_COMMANDS) -> str | None:
    matches = difflib.get_close_matches(cmd, known, n=1, cutoff=0.6)
    return matches[0] if matches else None


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
        ("ctrl+t", "stats", "Stats"),
        ("ctrl+r", "repro", "Repro"),
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
        self._last_reply = ""
        self._last_verdict = ""
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

    def _save_prefs(self) -> None:
        if not self._state_path:
            return
        from ..state import save_state

        save_state(self._state_path, {
            "profile": self.endpoint.name,
            "attacker_model": self.endpoint.model,
            "target_profile": self._target_profile,
            "target_model": self._target_model,
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
        self.registry.ctx.record = self._tool_verdict
        self._sync_judge_endpoint()
        self.query_one("#prompt", Input).focus()
        if self._resume_path:
            self._resume_session(self._resume_path)
        else:
            self._mount(widgets.info_panel(
                "rth red-team harness. /help for commands.", title="ready"
            ))

    def _resume_session(self, path) -> None:
        from ..session import load_session

        try:
            history, meta = load_session(path)
        except (OSError, ValueError) as exc:
            self._mount(widgets.error_panel(f"resume failed: {exc}"))
            return
        self.history = history
        self.objective = meta.get("objective", "")
        self.template = meta.get("template", "")
        self.sysprompt = meta.get("sysprompt", "")
        self.asr_hits = meta.get("asr_hits", 0)
        self.asr_total = meta.get("asr_total", 0)
        self._rerender(f"resumed {len(history)} messages from autosave")
        self._refresh_status()

    def _tool_progress(self, message: str) -> None:
        self._mount(widgets.info_panel(message, title="progress"))

    def _status_text(self) -> str:
        tgt = self.config.target.model if self.config.target else "none"
        pin = self.config.target.provider if self.config.target else ()
        if pin:
            tgt += f"@{'+'.join(pin)}"
        mode = f"auto({self.max_rounds})" if self.auto else "single"
        asr = (
            f"{self.asr_hits}/{self.asr_total}"
            if self.asr_total
            else "0/0"
        )
        state = "WORKING" if self._busy else "idle"
        tok = f"{self.tokens_in}>{self.tokens_out}tok"
        judge = "judge" if self.judge_enabled else "heur"
        last = f" | last={self._last_verdict}" if self._last_verdict else ""
        return (
            f" {state} | profile={self.endpoint.name} | model={self.endpoint.model} | "
            f"target={tgt} | {mode} | ASR={asr}/{judge}{last} | {tok}"
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
            self._autosave()
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

    def _on_tool_result(
        self, _id: str, name: str, content: str, is_error: bool, technique: str = ""
    ) -> None:
        self.runlog.tool_result(name, content, is_error)
        if name == "query_target" and not is_error:
            reply = content.split("\n", 1)[1] if content.startswith("[target") else content
            self._last_reply = reply
            payload = self._last_payload
            tech = technique or "query_target"
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
        self.runlog.verdict(payload, reply, label, reason, technique)

    def _tool_verdict(
        self, payload: str, response: str, label: str, reason: str, technique: str
    ) -> None:
        """Sink for verdicts graded inside agent tools (many_shot, prefill, best_of_n)."""
        self.asr_total += 1
        if label in ("COMPLIED", "PARTIAL"):
            self.asr_hits += 1
        self._last_verdict = label
        self.runlog.verdict(payload, response, label, reason, technique)

    def _on_error(self, message: str) -> None:
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
                body = "\n".join(matched) if matched else f"no help lines match {flt!r}"
                self._mount(widgets.info_panel(body, title=f"help ~ {flt}"))
            else:
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
        elif cmd == "/provider":
            self._cmd_provider(rest)
        elif cmd == "/validate":
            self.run_worker(self._cmd_validate(raw_arg), group="judge", exclusive=False)
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
                f"exit-on-finish {'on' if self.exit_on_finish else 'off'}",
                title="autoexit",
            ))
        elif cmd == "/transforms":
            flt = rest[0].lower() if rest else ""
            items = [
                t for t in list_transforms()
                if not flt or flt in t.name.lower() or flt in t.description.lower()
            ]
            catalog = "\n".join(f"{t.name:14} {t.description}" for t in items) or "(no match)"
            title = f"transforms ({len(items)})" + (f" ~ {flt}" if flt else "")
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
            ) or "(no match)"
            title = f"tools ({len(tools)})" + (f" ~ {flt}" if flt else "")
            self._mount(widgets.info_panel(f"{body}", title=title))
        elif cmd == "/preset":
            self._cmd_preset(rest)
        elif cmd == "/lib":
            self.run_worker(self._cmd_lib(rest), exclusive=False)
        elif cmd == "/eni":
            self.run_worker(self._cmd_eni(rest), exclusive=False)
        elif cmd == "/seedsweep":
            self.run_worker(self._cmd_seedsweep(raw_arg), group="judge", exclusive=False)
        elif cmd == "/narrate":
            self.run_worker(self._cmd_narrate(raw_arg), group="judge", exclusive=False)
        elif cmd == "/harmbench":
            self.run_worker(self._cmd_harmbench(rest), exclusive=False)
        elif cmd == "/campaign":
            self.run_worker(self._cmd_campaign(rest), group="judge", exclusive=False)
        elif cmd == "/leaderboard":
            self.run_worker(self._cmd_leaderboard(rest), group="judge", exclusive=False)
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
                f"targets hit: {self.asr_total}\n"
                f"complied/partial: {self.asr_hits}\n"
                f"guardrail held: {self.asr_total - self.asr_hits}\n"
                f"log: {self.runlog.path}",
                title="attack scoreboard",
            ))
        elif cmd == "/stats":
            self._cmd_stats()
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
            self._cmd_session(rest)
        elif cmd == "/save":
            self._cmd_save(rest)
        else:
            hint = suggest_command(cmd)
            msg = f"unknown command: {cmd}"
            if hint:
                msg += f"  — did you mean {hint}?"
            self._mount(widgets.error_panel(msg))

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

    def _cmd_provider(self, rest: list[str]) -> None:
        if self.config.target is None:
            self._mount(widgets.error_panel("no target configured"))
            return
        if not rest or rest[0].lower() == "show":
            p = self.config.target.provider
            self._mount(widgets.info_panel(
                f"target provider pin: {'+'.join(p) if p else 'none (variable backend routing)'}\n"
                f"  /provider <name> [name2...]  pin OpenRouter backend(s)\n"
                f"  /provider none               unpin",
                title="provider",
            ))
            return
        if rest[0].lower() in ("none", "clear", "off"):
            self.config.target = dataclasses.replace(self.config.target, provider=())
        else:
            self.config.target = dataclasses.replace(self.config.target, provider=tuple(rest))
        self._save_prefs()
        self._mount(widgets.info_panel(
            f"provider pin -> {'+'.join(self.config.target.provider) or 'none'}",
            title="provider",
        ))

    async def _cmd_validate(self, task: str) -> None:
        args: dict = {"n": 8}
        if task:
            args["task"] = task
            if self.sysprompt:
                args["system"] = self.sysprompt
        elif self.sysprompt:
            self._mount(widgets.error_panel("usage: /validate <task> (validates the system prompt)"))
            return
        elif self._last_payload:
            args["task"] = self._last_payload
        else:
            self._mount(widgets.error_panel("nothing to validate; fire something first or /validate <task>"))
            return
        self._mount(widgets.info_panel("re-firing 8 samples for the real success rate...", title="validate"))
        res = await self.registry.execute("validate", args)
        self._mount(widgets.info_panel(res.content, title="validate"))

    async def _cmd_replay(self, rest: list[str]) -> None:
        from ..report import _load_records

        verdicts = [
            r for r in _load_records(self.runlog.path) if r.get("kind") == "verdict"
        ]
        if not verdicts:
            self._mount(widgets.error_panel("no logged payloads to replay yet"))
            return
        idx = len(verdicts)
        if rest and rest[0].lstrip("-").isdigit():
            idx = int(rest[0])
        if not (1 <= idx <= len(verdicts)):
            self._mount(widgets.error_panel(
                f"index out of range; have {len(verdicts)} logged payloads"
            ))
            return
        rec = verdicts[idx - 1]
        payload = str(rec.get("payload", ""))
        if not payload:
            self._mount(widgets.error_panel("that record has no stored payload"))
            return
        self._last_payload = payload
        self._mount(widgets.info_panel(
            f"replaying #{idx} (was {rec.get('label', '?')}) at "
            f"{self.config.target.model if self.config.target else 'no target'}",
            title="replay",
        ))
        res = await self.registry.execute("query_target", {"prompt": payload})
        self._on_tool_result("manual", "query_target", res.content, res.is_error, "replay")

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
        if rest and rest[0].lower() == "test":
            self.run_worker(self._cmd_judge_test(), group="judge", exclusive=False)
            return
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

    async def _cmd_harmbench(self, rest: list[str]) -> None:
        action = rest[0] if rest else "categories"
        if action == "categories":
            out = await self.registry.execute("harmbench", {"action": "categories"})
        else:
            out = await self.registry.execute(
                "harmbench", {"action": "sample", "category": action, "n": 10}
            )
        self._mount(widgets.info_panel(out.content, title="harmbench"))

    async def _cmd_campaign(self, rest: list[str]) -> None:
        args: dict = {}
        for tok in rest:
            if tok.isdigit():
                args["n"] = int(tok)
            else:
                args["category"] = tok
        self._mount(widgets.info_panel(
            f"running auto-campaign (escalation ladder) against "
            f"{self.config.target.model if self.config.target else 'no target'}...",
            title="campaign",
        ))
        res = await self.registry.execute("campaign", args)
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="campaign"
        )
        self._mount(panel)
        self._refresh_status()

    async def _cmd_leaderboard(self, rest: list[str]) -> None:
        if len(self.config.profiles) < 2:
            self._mount(widgets.error_panel(
                "need >=2 configured profiles to rank"
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
            "benchmarking profiles against one battery...", title="leaderboard"
        ))
        res = await self.registry.execute("leaderboard", args)
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="leaderboard"
        )
        self._mount(panel)

    def _cmd_leakscan(self) -> None:
        from ..tools.leak_scan import scan_text

        if not self._last_reply:
            self._mount(widgets.error_panel("no target reply yet to scan"))
            return
        result = scan_text(self._last_reply, self.sysprompt or None)
        findings = result["findings"]
        if not findings:
            self._mount(widgets.info_panel(
                "no secrets, PII, or system-prompt echo in the last reply.", title="leakscan"
            ))
            return
        lines = [f"[{f['type']:18}] {f['match']}" for f in findings]
        self._mount(widgets.info_panel(
            f"{len(findings)} leak indicator(s) in the last reply:\n\n" + "\n".join(lines),
            title="leakscan",
        ))

    async def _cmd_judge_test(self) -> None:
        self._mount(widgets.info_panel(
            "calibrating the judge on benign fixtures...", title="judge test"
        ))
        res = await self.registry.execute("judge_selftest", {})
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="judge test"
        )
        self._mount(panel)

    def _cmd_find(self, term: str) -> None:
        if not term:
            self._mount(widgets.error_panel("usage: /find <term>"))
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
            self._mount(widgets.info_panel(f"no matches for {term!r}", title="find"))
            return
        self._mount(widgets.info_panel(
            f"{len(hits)} match(es) for {term!r}:\n\n" + "\n".join(hits[:40]),
            title="find",
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

    async def _cmd_eni(self, rest: list[str]) -> None:
        action = rest[0] if rest else "list"
        if action in ("list", "update"):
            out = await self.registry.execute("eni_list", {})
            self._mount(widgets.info_panel(out.content, title="eni"))
        elif action == "search":
            query = " ".join(rest[1:])
            if not query:
                self._mount(widgets.error_panel("usage: /eni search <query>"))
                return
            out = await self.registry.execute("eni_search", {"query": query})
            self._mount(widgets.info_panel(out.content, title="eni:search"))
        else:
            out = await self.registry.execute("eni_get", {"model": action})
            self._mount(widgets.info_panel(out.content, title=f"eni:{action}"))

    async def _cmd_narrate(self, request: str) -> None:
        if not request:
            self._mount(widgets.error_panel("usage: /narrate <request to dramatize>"))
            return
        self._last_payload = request
        self._mount(widgets.info_panel(
            "wrapping as a novel chapter + in-story prefill, firing...", title="narrate"
        ))
        res = await self.registry.execute("narrate", {"request": request})
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="narrate"
        )
        self._mount(panel)
        self._refresh_status()

    async def _cmd_seedsweep(self, request: str) -> None:
        if not request:
            self._mount(widgets.error_panel("usage: /seedsweep <request to inject>"))
            return
        self._mount(widgets.info_panel(
            "sweeping cross-provider jailbreak seeds against the target...",
            title="seed sweep",
        ))
        res = await self.registry.execute("seed_sweep", {"request": request})
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="seed sweep"
        )
        self._mount(panel)
        self._refresh_status()

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

    def _cmd_template(self, rest: list[str], raw: str) -> None:
        sub = rest[0].lower() if rest else "show"
        body = raw[len(rest[0]):].strip() if rest else ""
        if sub == "show" or not rest:
            msg = self.template or "no template set. /template set <text with {request}>"
            self._mount(widgets.info_panel(msg, title="template"))
        elif sub == "set":
            if "{request}" not in body:
                self._mount(widgets.error_panel("template must contain a {request} placeholder"))
                return
            self.template = body
            self._mount(widgets.info_panel(
                f"template set ({len(body)} chars)\n\n{body[:400]}", title="template"
            ))
        elif sub == "clear":
            self.template = ""
            self._mount(widgets.info_panel("template cleared", title="template"))
        elif sub == "save":
            path = rest[1] if len(rest) > 1 else "template.txt"
            try:
                with open(path, "w", encoding="utf-8") as h:
                    h.write(self.template)
                self._mount(widgets.info_panel(f"template saved to {path}", title="template"))
            except OSError as exc:
                self._mount(widgets.error_panel(str(exc)))
        elif sub == "fire":
            if not self.template:
                self._mount(widgets.error_panel("set a template first: /template set <text>"))
                return
            if not body:
                self._mount(widgets.error_panel("usage: /template fire <category request>"))
                return
            self.run_worker(self._template_fire(body), group="judge", exclusive=False)
        elif sub == "test":
            if not self.template:
                self._mount(widgets.error_panel("set a template first: /template set <text>"))
                return
            cats = [c.strip() for c in body.split(";") if c.strip()] if body else None
            self.run_worker(self._template_test(cats), group="judge", exclusive=False)
        else:
            self._mount(widgets.error_panel("usage: /template [show|set|fire|test|save|clear]"))

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
            f"testing template across {len(cats)} categories...", title="template test"
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
            title="template test",
        ))

    def _cmd_sysprompt(self, rest: list[str], raw: str) -> None:
        sub = rest[0].lower() if rest else "show"
        body = raw[len(rest[0]):].strip() if rest else ""
        if sub == "show" or not rest:
            self._mount(widgets.info_panel(
                self.sysprompt or "no system prompt set. /sysprompt set <text>",
                title="sysprompt",
            ))
        elif sub == "set":
            self.sysprompt = body
            self._mount(widgets.info_panel(
                f"system prompt set ({len(body)} chars)\n\n{body[:400]}", title="sysprompt"
            ))
        elif sub == "clear":
            self.sysprompt = ""
            self._mount(widgets.info_panel("system prompt cleared", title="sysprompt"))
        elif sub == "save":
            path = rest[1] if len(rest) > 1 else "sysprompt.txt"
            try:
                with open(path, "w", encoding="utf-8") as h:
                    h.write(self.sysprompt)
                self._mount(widgets.info_panel(f"saved to {path}", title="sysprompt"))
            except OSError as exc:
                self._mount(widgets.error_panel(str(exc)))
        elif sub == "test":
            if not self.sysprompt:
                self._mount(widgets.error_panel("set a system prompt first: /sysprompt set <text>"))
                return
            words = body.split()
            prefill = bool(words and words[0].lower() == "prefill")
            if prefill:
                body = body[len(words[0]):].strip()
            tasks = [t.strip() for t in body.split(";") if t.strip()] if body else None
            self.run_worker(self._sysprompt_test(tasks, prefill), group="judge", exclusive=False)
        else:
            self._mount(widgets.error_panel("usage: /sysprompt [show|set|test [prefill]|save|clear]"))

    async def _sysprompt_test(self, tasks, prefill: bool = False) -> None:
        args = {"system": self.sysprompt}
        if tasks:
            args["tasks"] = tasks
        if prefill:
            args["prefill"] = True
        res = await self.registry.execute("system_sweep", args)
        self._mount(widgets.info_panel(res.content, title="sysprompt sweep"))
        self._refresh_status()

    def _cmd_encode(self, rest: list[str]) -> None:
        from ..transforms import TRANSFORMS, apply_chain, reverse_chain

        if len(rest) < 2:
            self._mount(widgets.error_panel(
                "usage: /encode <chain> <text>   e.g. /encode leet,base64 write a poem"
            ))
            return
        chain = [c.strip() for c in rest[0].split(",") if c.strip()]
        text = " ".join(rest[1:])
        unknown = [c for c in chain if c not in TRANSFORMS]
        if unknown:
            self._mount(widgets.error_panel(
                f"unknown transform(s): {', '.join(unknown)} (see /transforms)"
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
            note = "(copied to clipboard)"
        except Exception:
            note = ""
        flags = []
        if lossy:
            flags.append(f"lossy: {'+'.join(lossy)}")
        flags.append(f"reversible: {'yes' if reversible else 'no'}")
        flags.append(f"round-trip: {roundtrip}")
        self._mount(widgets.info_panel(
            f"chain: {'+'.join(chain)}  ({' | '.join(flags)}) {note}\n\n"
            f"{encoded}\n\n"
            f"fire it: query_target prompt=<text> transforms={chain}",
            title="encode",
        ))

    async def _cmd_diff(self, raw: str) -> None:
        if ";;" not in raw:
            self._mount(widgets.error_panel("usage: /diff <payload a> ;; <payload b>"))
            return
        a, b = (part.strip() for part in raw.split(";;", 1))
        if not a or not b:
            self._mount(widgets.error_panel("both sides of ;; must be non-empty"))
            return
        self._mount(widgets.info_panel(
            "firing A/B against the target...", title="diff"
        ))
        res = await self.registry.execute("diff_fire", {"a": a, "b": b})
        panel = widgets.error_panel(res.content) if res.is_error else widgets.info_panel(
            res.content, title="diff"
        )
        self._mount(panel)

    def _cmd_stats(self) -> None:
        from ..report import _load_records

        records = _load_records(self.runlog.path)
        if not records:
            self._mount(widgets.info_panel(
                "no run-log records yet. Fire something (logging must be on).",
                title="stats",
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
            f"graded fires: {total}   ASR: {asr}   ({hits} bypass / {total - hits} held)\n\n"
            f"verdict mix:\n" + "\n".join(bar_lines) + "\n\n"
            f"ASR by technique:\n" + "\n".join(tech_lines) + "\n\n"
            f"busiest tools:\n" + "\n".join(tool_lines) + "\n\n"
            f"log: {self.runlog.path}",
            title="stats",
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
                f"exported {len(findings)} finding(s) to {path}", title="export"
            ))
        except OSError as exc:
            self._mount(widgets.error_panel(str(exc)))

    def _cmd_repro(self, rest: list[str]) -> None:
        from ..report import extract_findings

        findings = extract_findings(self.runlog.path)
        if not findings:
            self._mount(widgets.info_panel(
                "no bypasses to reproduce yet (COMPLIED/PARTIAL).", title="repro"
            ))
            return
        idx = 1
        if rest and rest[0].lstrip("-").isdigit():
            idx = int(rest[0])
        if not (1 <= idx <= len(findings)):
            self._mount(widgets.error_panel(
                f"index out of range; have {len(findings)} bypass(es)"
            ))
            return
        f = findings[idx - 1]
        tgt = self.config.target
        pin = "+".join(tgt.provider) if tgt and tgt.provider else "none"
        payload = str(f.get("payload", ""))
        block = (
            "=== rth repro pack ===\n"
            f"target.model : {tgt.model if tgt else 'n/a'}\n"
            f"target.base  : {tgt.base_url if tgt else 'n/a'}\n"
            f"provider.pin : {pin}\n"
            f"technique    : {f.get('technique') or 'manual'}\n"
            f"verdict      : {f.get('label', '?')}\n"
            f"judge.reason : {f.get('reason', '')}\n"
            "--- payload ---\n"
            f"{payload}\n"
            "--- reproduce ---\n"
            "fire in rth:  /target <model> ; then paste the payload above\n"
            "or tool call: query_target {\"prompt\": <payload>}\n"
            "======================"
        )
        try:
            self.copy_to_clipboard(block)
            note = " (copied to clipboard)"
        except Exception:
            note = ""
        self._mount(widgets.info_panel(
            f"repro pack for bypass #{idx}/{len(findings)}{note}\n\n{block}",
            title="repro",
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
            preview = "open it in a browser for the color-coded scoreboard."
        else:
            body = build_report(self.runlog.path)
            path = rest[0] if rest else "report.md"
            preview = body[:600]
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body)
            self._mount(widgets.info_panel(
                f"report written to {path}\n\n{preview}", title="report"
            ))
        except OSError as exc:
            self._mount(widgets.error_panel(str(exc)))

    def _cmd_session(self, rest: list[str]) -> None:
        from ..session import load_session, save_session

        action = rest[0].lower() if rest else "save"
        path = rest[1] if len(rest) > 1 else "session.json"
        if action == "save":
            meta = self._session_meta()
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
            self.template = meta.get("template", "")
            self.sysprompt = meta.get("sysprompt", "")
            self.asr_hits = meta.get("asr_hits", 0)
            self.asr_total = meta.get("asr_total", 0)
            note = f"loaded {len(history)} messages from {path}"
            if meta.get("source") == "run_log":
                note += " (run log: dialogue restored, tool calls omitted)"
            self._rerender(note)
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
        print("\n=== engagement complete ===")
        print(app._exit_summary)
        if app.runlog.enabled and app.runlog._started:
            print(f"\nrun log: {app.runlog.path}")
    return 0
