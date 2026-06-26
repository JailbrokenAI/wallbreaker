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


SUBCOMMANDS = ("lib", "transform")


def build_main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rth", description="Red-team harness: a configurable agentic LLM terminal"
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
    return parser


def build_sub_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rth")
    sub = parser.add_subparsers(dest="command", required=True)

    lib = sub.add_parser("lib", help="Manage the L1B3RT4S jailbreak library")
    lib.add_argument("lib_action", choices=["update", "list", "path"])

    tr = sub.add_parser("transform", help="Run Parseltongue transforms on text")
    tr.add_argument("transforms", help="Comma-separated transform chain, e.g. leet,base64")
    tr.add_argument("text", nargs="?", help="Text (or read stdin)")
    tr.add_argument("--decode", action="store_true", help="Reverse the chain")

    return parser


async def _one_shot(config: Config, args: argparse.Namespace) -> int:
    from .agent.messages import user
    from .providers.factory import build_provider

    endpoint = resolve_endpoint(config, args)
    provider = build_provider(endpoint)
    from .agent.messages import TextDelta

    try:
        async for event in provider.stream([user(args.prompt)], max_tokens=4096):
            if isinstance(event, TextDelta):
                sys.stdout.write(event.text)
                sys.stdout.flush()
    except ProviderError as exc:
        print(f"\n[provider error] {exc}", file=sys.stderr)
        return 1
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    first_pos = next((a for a in raw if not a.startswith("-")), None)

    if first_pos in SUBCOMMANDS:
        args = build_sub_parser().parse_args(raw)
        if args.command == "transform":
            from .tools.parseltongue import run_chain_cli

            return run_chain_cli(args)
        from .tools.l1b3rt4s import run_lib_cli

        return run_lib_cli(args)

    args = build_main_parser().parse_args(raw)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"[config error] {exc}", file=sys.stderr)
        return 1

    if args.prompt:
        return asyncio.run(_one_shot(config, args))

    from .tui.app import run_tui

    return run_tui(config, args)


if __name__ == "__main__":
    raise SystemExit(main())
