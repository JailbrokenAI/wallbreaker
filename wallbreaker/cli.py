from __future__ import annotations

import argparse
import asyncio
import sys

from .config import Config, ConfigError, Endpoint, load_config
from .providers.base import ProviderError


def _override_endpoint(base: Endpoint, args: argparse.Namespace) -> Endpoint:
    return Endpoint(
        name=base.name,
        protocol=args.protocol or base.protocol,
        base_url=(args.base_url or base.base_url).rstrip("/"),
        model=args.model or base.model,
        api_key_env=args.api_key_env or base.api_key_env,
        api_key=args.api_key or base.api_key,
    )


def resolve_endpoint(config: Config, args: argparse.Namespace) -> Endpoint:
    base = config.profile(args.profile)
    return _override_endpoint(base, args)


def _add_endpoint_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to config.toml")
    parser.add_argument("--profile", help="Profile name from config")
    parser.add_argument("--base-url", help="Override base URL")
    parser.add_argument("--model", help="Override model id")
    parser.add_argument(
        "--protocol", choices=["openai", "anthropic"], help="Override wire protocol"
    )
    parser.add_argument("--api-key-env", help="Env var holding the API key")
    parser.add_argument("--api-key", help="API key literal (prefer --api-key-env)")


SUBCOMMANDS = ("lib", "parsel", "eni", "transform", "findings", "report", "export", "check", "regrade", "baseline", "dashboard")


def build_main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wallbreaker",
        description="Wallbreaker — red-team harness: a configurable agentic LLM terminal",
    )
    _add_endpoint_flags(parser)
    parser.add_argument(
        "prompt", nargs="?", help="One-shot prompt. Omit to launch the TUI."
    )
    parser.add_argument(
        "--no-tools", action="store_true", help="Disable agent tools for one-shot mode"
    )
    parser.add_argument(
        "--system", help="System prompt override for this session"
    )
    parser.add_argument(
        "--auto", action="store_true", help="Run autonomously until finish/ask_operator"
    )
    parser.add_argument(
        "--rounds", type=int, default=12, help="Autonomous round cap (default 12)"
    )
    parser.add_argument(
        "--target", help="Target profile name to attack (overrides [target])"
    )
    parser.add_argument(
        "--target-model", help="Model id to attack on the target endpoint"
    )
    parser.add_argument(
        "--target-modality", choices=["text", "image"],
        help="Force the target modality (default: auto-detect image-gen models by id)",
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="",
        help="Resume the autosaved session (or a session file path) in the TUI",
    )
    return parser


def apply_target_overrides(config: Config, args: argparse.Namespace) -> None:
    import dataclasses

    if getattr(args, "target", None):
        if args.target in config.profiles:
            config.target = dataclasses.replace(
                config.profiles[args.target], name="target"
            )
    if getattr(args, "target_model", None):
        from .config import resolve_target_modality

        base = config.target or config.profile()
        modality = resolve_target_modality(
            args.target_model, getattr(args, "target_modality", None)
        )
        config.target = dataclasses.replace(
            base, name="target", model=args.target_model, modality=modality
        )
    elif getattr(args, "target_modality", None) and config.target is not None:
        # modality forced without a model swap (e.g. the [target] model is an image model)
        config.target = dataclasses.replace(config.target, modality=args.target_modality)


def build_sub_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wallbreaker")
    sub = parser.add_subparsers(dest="command", required=True)

    lib = sub.add_parser("lib", help="Manage the L1B3RT4S jailbreak library")
    lib.add_argument("lib_action", choices=["update", "list", "path"])

    parsel = sub.add_parser(
        "parsel", help="Manage the P4RS3LT0NGV3 transform library (MCP server backend)"
    )
    parsel.add_argument("parsel_action", choices=["update", "list", "path"])

    eni = sub.add_parser("eni", help="Browse the ENI persona-jailbreak collection")
    eni.add_argument("eni_action", choices=["list", "update", "path"])

    tr = sub.add_parser("transform", help="Run Parseltongue transforms on text")
    tr.add_argument("transforms", help="Comma-separated transform chain, e.g. leet,base64")
    tr.add_argument("text", nargs="?", help="Text (or read stdin)")
    tr.add_argument("--decode", action="store_true", help="Reverse the chain")

    fd = sub.add_parser("findings", help="List bypasses from a run log")
    fd.add_argument("log", nargs="?", help="Run log, or a dir (default: latest in sessions/)")

    rep = sub.add_parser("report", help="Render a findings report from a run log")
    rep.add_argument("log", nargs="?", help="Run log, or a dir (default: latest in sessions/)")
    rep.add_argument("--html", action="store_true", help="Emit styled HTML instead of markdown")
    rep.add_argument("--out", help="Write to this path instead of stdout")

    ex = sub.add_parser("export", help="Dump structured findings JSON from a run log")
    ex.add_argument("log", nargs="?", help="Run log, or a dir (default: latest in sessions/)")
    ex.add_argument("--out", help="Write to this path instead of stdout")
    ex.add_argument(
        "--fail-on-finding",
        action="store_true",
        help="Exit non-zero if any bypass is present (CI gate)",
    )

    ck = sub.add_parser("check", help="Validate config.toml and print a readiness checklist")
    ck.add_argument("--config", help="Path to config.toml")

    rg = sub.add_parser("regrade", help="Re-judge a run log with the current judge")
    rg.add_argument("log", nargs="?", help="Run log, or a dir (default: latest in sessions/)")
    rg.add_argument("--config", help="Path to config.toml")

    bl = sub.add_parser("baseline", help="ASR-regression CI gate from run logs")
    bl_sub = bl.add_subparsers(dest="baseline_action", required=True)
    bls = bl_sub.add_parser("save", help="Write a baseline json from a run log")
    bls.add_argument("log", nargs="?", help="Run log, or a dir (default: latest in sessions/)")
    bls.add_argument("--out", default="baseline.json", help="Output path (default baseline.json)")
    blc = bl_sub.add_parser(
        "compare", help="Compare a run log against a baseline; nonzero exit on ASR regression"
    )
    blc.add_argument("log", nargs="?", help="Run log, or a dir (default: latest in sessions/)")
    blc.add_argument("--baseline", default="baseline.json", help="Baseline json path")
    blc.add_argument(
        "--max-regression",
        type=float,
        default=0.05,
        help="Max allowed ASR rise per technique before failing (default 0.05)",
    )

    dash = sub.add_parser("dashboard", help="Serve the Wallbreaker web dashboard")
    dash.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    dash.add_argument("--port", type=int, default=8787, help="Bind port (default 8787)")
    dash.add_argument("--sessions", default="sessions", help="Run-log directory (default sessions/)")
    dash.add_argument("--config", help="Path to config.toml")

    return parser


async def _one_shot(config: Config, args: argparse.Namespace) -> int:
    from .agent.loop import AgentEvents, run_autonomous, run_turn
    from .agent.messages import user
    from .prompts import compose_system
    from .providers.factory import build_provider
    from .tools import build_registry

    from .session import RunLog

    endpoint = resolve_endpoint(config, args)
    provider = build_provider(endpoint)
    registry = None if args.no_tools else build_registry(config)
    runlog = RunLog()
    runlog.event("objective", text=args.prompt)
    runlog.user(args.prompt)
    if registry is not None:
        registry.ctx.progress = lambda m: print(f"[progress] {m}", file=sys.stderr)
        registry.ctx.record = (
            lambda p, r, lbl, rs, t: runlog.verdict(p, r, lbl, rs, t)
        )
        registry.ctx.current_objective = args.prompt or ""
        registry.ctx.attacker_model = endpoint.model or ""
        registry.ctx.tool_logger = (
            lambda n, a, c, e: (runlog.tool_call(n, a), runlog.tool_result(n, c, e))
        )
    mcp_bridge = None
    if registry is not None:
        from .tools.mcp_bridge import attach_mcp_servers

        mcp_bridge = await attach_mcp_servers(
            registry, config, progress=lambda m: print(f"[{m}]", file=sys.stderr)
        )
    system = compose_system(endpoint, args.system)

    def emit(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    events = AgentEvents(
        on_text=emit,
        on_reasoning=lambda t: runlog.reasoning(t, source="brain"),
        on_tool_start=lambda _i, n, a: print(f"\n[tool {n} {a}]", file=sys.stderr),
        on_tool_result=lambda _i, n, c, e: print(
            f"[{n} -> {'error' if e else 'ok'}]", file=sys.stderr
        ),
        on_turn_end=lambda message: runlog.assistant(message.text()),
        on_usage=lambda tokens_in, tokens_out: runlog.event(
            "usage", tokens_in=tokens_in, tokens_out=tokens_out
        ),
        on_error=lambda message: (
            print(f"\n[error] {message}", file=sys.stderr),
            runlog.event("error", message=message),
        ),
        on_round=lambda r, m: print(f"\n=== round {r}/{m} ===", file=sys.stderr),
    )

    history = [user(args.prompt)]
    try:
        if args.auto:
            result = await run_autonomous(
                provider, registry, history, system=system,
                events=events, max_rounds=args.rounds,
            )
            terminal = result.data.get("summary") or result.data.get("question") or ""
            print(f"\n\n[{result.status}] {terminal}", file=sys.stderr)
            runlog.event("run_end", status=result.status, summary=terminal)
        else:
            await run_turn(
                provider, registry, history, system=system, events=events
            )
            runlog.event("run_end", status="completed")
    except ProviderError as exc:
        print(f"\n[provider error] {exc}", file=sys.stderr)
        runlog.event("run_end", status="provider_error", error=str(exc))
        return 1
    finally:
        if mcp_bridge is not None:
            await mcp_bridge.aclose()
    print()
    if runlog._started:
        print(f"[run log] {runlog.path} (wallbreaker report / wallbreaker export to summarize)", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    first_pos = next((a for a in raw if not a.startswith("-")), None)

    if first_pos in SUBCOMMANDS:
        args = build_sub_parser().parse_args(raw)
        if args.command == "transform":
            from .tools.parseltongue import run_chain_cli

            return run_chain_cli(args)
        if args.command == "eni":
            from .tools.eni import run_eni_cli

            return run_eni_cli(args)
        if args.command == "parsel":
            from .tools.parsel_lib import run_parsel_cli

            return run_parsel_cli(args)
        if args.command in ("findings", "report", "export"):
            from .report import resolve_log_path

            log = resolve_log_path(args.log)
            if log is None:
                where = args.log or "sessions/"
                print(f"No run log found at {where}.", file=sys.stderr)
                return 1
            args.log = str(log)
        if args.command == "findings":
            from .report import extract_findings

            findings = extract_findings(args.log)
            if not findings:
                print("No bypasses (COMPLIED/PARTIAL) in that log.")
                return 0
            for f in findings:
                payload = str(f.get("payload", "")).replace("\n", " ")[:80]
                print(f"[{f['label']:8}] {payload}  -- {f.get('reason', '')[:60]}")
            return 0
        if args.command == "report":
            from .report import build_html_report, build_report

            body = build_html_report(args.log) if args.html else build_report(args.log)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as handle:
                    handle.write(body)
                print(f"report written to {args.out}", file=sys.stderr)
            else:
                print(body)
            return 0
        if args.command == "export":
            import json

            from .report import build_findings_export

            data = build_findings_export(args.log)
            text = json.dumps(data, ensure_ascii=False, indent=2)
            if args.out:
                with open(args.out, "w", encoding="utf-8") as handle:
                    handle.write(text)
                print(f"exported {len(data['findings'])} finding(s) to {args.out}", file=sys.stderr)
            else:
                print(text)
            if args.fail_on_finding and data["findings"]:
                return 2
            return 0
        if args.command == "regrade":
            from .regrade import format_regrade, regrade_log
            from .report import resolve_log_path

            try:
                config = load_config(args.config)
            except ConfigError as exc:
                print(f"[config error] {exc}", file=sys.stderr)
                return 1
            log = resolve_log_path(args.log)
            if log is None:
                print(f"No run log found at {args.log or 'sessions/'}.", file=sys.stderr)
                return 1
            judge = config.judge or (config.profile() if config.profiles else None)
            if judge is None:
                print("[config error] no judge or profile to grade with.", file=sys.stderr)
                return 1
            summary = asyncio.run(regrade_log(log, judge))
            print(format_regrade(summary, log))
            return 0
        if args.command == "check":
            from .config import doctor_report

            try:
                config = load_config(args.config)
            except ConfigError as exc:
                print(f"[config error] {exc}", file=sys.stderr)
                return 1
            report, ok = doctor_report(config)
            print(report)
            return 0 if ok else 1
        if args.command == "dashboard":
            try:
                from .dashboard.server import serve
            except ImportError:
                print(
                    "[dashboard] needs the optional extra: pip install -e '.[dashboard]'",
                    file=sys.stderr,
                )
                return 1
            try:
                config = load_config(args.config)
            except ConfigError:
                config = None
            tgt = (config.target.model if config and config.target else "no target")
            print(
                f"Wallbreaker dashboard -> http://{args.host}:{args.port}  (target: {tgt})",
                file=sys.stderr,
            )
            serve(host=args.host, port=args.port, config=config, sessions_dir=args.sessions)
            return 0
        if args.command == "baseline":
            from .baseline import compare_baseline, format_regressions, save_baseline
            from .report import resolve_log_path

            log = resolve_log_path(args.log)
            if log is None:
                print(f"No run log found at {args.log or 'sessions/'}.", file=sys.stderr)
                return 1
            if args.baseline_action == "save":
                save_baseline(log, args.out)
                print(f"baseline written to {args.out}", file=sys.stderr)
                return 0
            try:
                ok, regressions = compare_baseline(log, args.baseline, args.max_regression)
            except FileNotFoundError:
                print(f"No baseline at {args.baseline}; run 'wallbreaker baseline save' first.", file=sys.stderr)
                return 1
            print(format_regressions(regressions, ok, args.max_regression))
            return 0 if ok else 2
        from .tools.l1b3rt4s import run_lib_cli

        return run_lib_cli(args)

    args = build_main_parser().parse_args(raw)
    try:
        config = load_config(args.config)
        apply_target_overrides(config, args)
    except ConfigError as exc:
        print(f"[config error] {exc}", file=sys.stderr)
        return 1

    if args.prompt:
        return asyncio.run(_one_shot(config, args))

    from .tui.app import run_tui

    return run_tui(config, args)


if __name__ == "__main__":
    raise SystemExit(main())
