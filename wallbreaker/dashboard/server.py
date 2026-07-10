from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from datetime import datetime
from pathlib import Path

from .. import report as report_mod
from ..presets import list_presets
from ..transforms import TRANSFORMS, apply_chain, list_transforms

_VERDICT_RE = re.compile(r"\b(COMPLIED|PARTIAL|REFUSED|EMPTY|BLOCKED_INPUT|BLOCKED_OUTPUT)\b")
_RUN_NAME_RE = re.compile(r"^run-(\d{8})-?(\d{6})\.jsonl$")
_FIRE_TOOLS = {"query_target", "continue_target", "fire", "query_image_target"}
_FINDING_KINDS = {"verdict", "attack_fire"}
_FINDING_LABELS = {"COMPLIED", "PARTIAL"}


def _run_time_from_name(name: str) -> str:
    match = _RUN_NAME_RE.match(name)
    if not match:
        return ""
    try:
        dt = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    except ValueError:
        return ""
    return dt.isoformat(sep=" ", timespec="seconds")


def _models_from_records(records: list[dict]) -> dict:
    for record in records:
        if record.get("kind") != "run_meta":
            continue
        models = record.get("models")
        if isinstance(models, dict):
            return {
                "attacker": str(models.get("attacker") or ""),
                "target": str(models.get("target") or ""),
                "judge": str(models.get("judge") or ""),
                "recorded": True,
            }
    return {"attacker": "", "target": "", "judge": "", "recorded": False}


def _safe_run_path(sessions: Path, name: str) -> Path | None:
    if ".." in name or "/" in name or "\\" in name:
        return None
    path = sessions / name
    return path if path.is_file() else None


def _load_records_with_lines(path: Path) -> tuple[list[dict], list[str], list[int]]:
    records = []
    raw_records = []
    line_numbers = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = line.strip()
        if not raw:
            continue
        raw_records.append(raw)
        line_numbers.append(lineno)
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            records.append({
                "kind": "parse_error",
                "line": lineno,
                "error": str(exc),
                "raw": raw,
            })
    return records, raw_records, line_numbers


def _text_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


def _dict_value(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list_value(value) -> list:
    return value if isinstance(value, list) else []


def _split_chain(value) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _record_prompt(record: dict) -> str:
    args = _dict_value(record.get("args") or record.get("input"))
    for key in ("payload", "prompt", "request", "text", "objective", "query"):
        value = _text_value(record.get(key)).strip()
        if value:
            return value
    for key in ("payload", "prompt", "request", "text", "objective", "query"):
        value = _text_value(args.get(key)).strip()
        if value:
            return value
    return ""


def _record_response(record: dict) -> str:
    for key in ("response", "content", "result", "answer", "output", "text"):
        value = _text_value(record.get(key)).strip()
        if value:
            return value
    return ""


def _conversation_from_record(record: dict) -> list[dict]:
    for key in ("conversation", "history", "messages"):
        turns = _list_value(record.get(key))
        if not turns:
            continue
        out = []
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "user")
            content = _text_value(turn.get("content") or turn.get("text"))
            if content:
                out.append({"role": role, "content": content, "source": key})
        if out:
            return out
    return []


def _related_fire_records(records: list[dict], index: int) -> list[dict]:
    start = 0
    for i in range(index - 1, -1, -1):
        if records[i].get("kind") in _FINDING_KINDS:
            start = i + 1
            break
    related = []
    for record in records[start : index + 1]:
        kind = record.get("kind")
        tool = record.get("tool") or record.get("name")
        if kind in ("tool_call", "tool_result") and tool in _FIRE_TOOLS:
            related.append(record)
        elif kind in _FINDING_KINDS:
            related.append(record)
    return related


def _conversation_for_finding(records: list[dict], index: int, finding: dict) -> list[dict]:
    explicit = _conversation_from_record(finding)
    if explicit:
        return explicit

    turns = []
    for record in _related_fire_records(records, index):
        kind = record.get("kind")
        tool = str(record.get("tool") or record.get("name") or kind or "")
        if kind == "tool_call":
            args = _dict_value(record.get("args") or record.get("input"))
            for turn in _list_value(args.get("history")):
                if isinstance(turn, dict):
                    content = _text_value(turn.get("content") or turn.get("text"))
                    if content:
                        turns.append({
                            "role": str(turn.get("role") or "user"),
                            "content": content,
                            "source": f"{tool}:history",
                        })
            prompt = _record_prompt(record)
            if prompt:
                turns.append({"role": "user", "content": prompt, "source": tool})
        elif kind == "tool_result":
            response = _record_response(record)
            if response:
                turns.append({"role": "assistant", "content": response, "source": tool})

    if not turns:
        payload = _text_value(finding.get("payload")).strip()
        response = _text_value(finding.get("response")).strip()
        if payload:
            turns.append({"role": "user", "content": payload, "source": "finding"})
        if response:
            turns.append({"role": "assistant", "content": response, "source": "finding"})
    return turns


def _template_for_finding(records: list[dict], index: int, finding: dict) -> dict:
    related = _related_fire_records(records, index)
    args = {}
    source_tool = ""
    for record in reversed(related):
        if record.get("kind") != "tool_call":
            continue
        tool = str(record.get("tool") or record.get("name") or "")
        if tool not in _FIRE_TOOLS:
            continue
        args = _dict_value(record.get("args") or record.get("input"))
        source_tool = tool
        break

    def pick(*keys):
        for source in (finding, args):
            for key in keys:
                value = source.get(key)
                if value not in (None, "", [], {}):
                    return value
        return ""

    transforms = {
        "prompt": _split_chain(pick("transforms", "transform_chain", "obfuscation_chain")),
        "system": _split_chain(pick("system_transforms")),
        "response": _split_chain(pick("response_transforms")),
    }
    return {
        "technique": _text_value(pick("technique") or "manual"),
        "source_tool": source_tool,
        "preset": _text_value(pick("preset")),
        "template": _text_value(pick("template", "prompt_template", "technique_template")),
        "instructions": _text_value(pick("instructions", "system", "persona", "method")),
        "think_seed": _text_value(pick("think_seed")),
        "max_tokens": pick("max_tokens"),
        "transforms": transforms,
        "raw_args": args,
    }


def _judging_for_finding(finding: dict) -> dict:
    from ..judging import IMAGE_JUDGE_SYSTEM, IMAGE_JUDGE_TEMPLATE, JUDGE_SYSTEM, JUDGE_TEMPLATE

    source = _text_value(finding.get("judge_source") or finding.get("source") or "judge")
    is_image = source == "image-judge" or bool(finding.get("image_urls"))
    return {
        "source": source,
        "label": finding.get("label", ""),
        "reason": finding.get("reason", ""),
        "score": finding.get("score"),
        "criteria": IMAGE_JUDGE_SYSTEM if is_image else JUDGE_SYSTEM,
        "template": IMAGE_JUDGE_TEMPLATE if is_image else JUDGE_TEMPLATE,
    }


def _findings_for_run(path: Path) -> list[dict]:
    records, raw_records, line_numbers = _load_records_with_lines(path)
    models = _models_from_records(records)
    run_time = _run_time_from_name(path.name)
    findings = []
    for index, record in enumerate(records):
        label = str(record.get("label", "")).upper()
        if record.get("kind") not in _FINDING_KINDS or label not in _FINDING_LABELS:
            continue
        raw_line = raw_records[index] if index < len(raw_records) else json.dumps(record, ensure_ascii=False)
        line_number = line_numbers[index] if index < len(line_numbers) else index + 1
        finding = dict(record)
        finding.setdefault("label", label)
        finding["id"] = f"{path.name}:{line_number}"
        finding["run"] = path.name
        finding["run_time"] = run_time
        finding["line"] = line_number
        finding["record_index"] = index
        finding["raw"] = raw_line
        finding["models"] = models
        finding["conversation"] = _conversation_for_finding(records, index, record)
        finding["technique_detail"] = _template_for_finding(records, index, record)
        finding["judging"] = _judging_for_finding(record)
        finding["fields"] = record
        findings.append(finding)
    rank = {"COMPLIED": 0, "PARTIAL": 1}
    findings.sort(key=lambda item: (item.get("run", ""), rank.get(item.get("label"), 9), item.get("line", 0)), reverse=True)
    return findings


def _finding_run_summaries(sessions: Path) -> list[dict]:
    if not sessions.is_dir():
        return []
    out = []
    for path in sorted(sessions.glob("run-*.jsonl"), reverse=True):
        try:
            records = report_mod._load_records(path)
            findings_count = sum(
                1 for record in records
                if record.get("kind") in _FINDING_KINDS
                and str(record.get("label", "")).upper() in _FINDING_LABELS
            )
            hits = sum(
                1 for record in records
                if str(record.get("label", "")).upper() in _FINDING_LABELS
            )
        except Exception:
            records, findings_count, hits = [], 0, 0
        out.append({
            "name": path.name,
            "time": _run_time_from_name(path.name),
            "models": _models_from_records(records),
            "size": path.stat().st_size,
            "records": len(records),
            "hits": hits,
            "findings": findings_count,
        })
    return out


def _summarize_args(args: dict) -> str:
    if not isinstance(args, dict):
        return str(args)[:300]
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        if k in ("prompt", "request", "text", "payload") and isinstance(v, str):
            parts.append(f"{k}({len(v)} chars): {v[:160]}")
        else:
            vs = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            parts.append(f"{k}={str(vs)[:120]}")
    return "  ".join(parts)[:600]


def _web_dist(web_dir: str | Path | None) -> Path | None:
    base = Path(web_dir) if web_dir else Path(__file__).resolve().parent / "web"
    dist = base / "dist"
    return dist if dist.is_dir() and (dist / "index.html").is_file() else None


def _config_summary(config) -> dict:
    if config is None:
        return {"has_target": False, "target": None, "profile": None, "judge": None}
    target = getattr(config, "target", None)
    judge = getattr(config, "judge", None)
    prof = None
    try:
        prof = config.default_profile
    except Exception:
        prof = None
    return {
        "has_target": target is not None,
        "target": getattr(target, "model", None) if target else None,
        "target_modality": getattr(target, "modality", "text") if target else None,
        "profile": prof,
        "judge": getattr(judge, "model", None) if judge else None,
    }


def _extract_verdict(text: str) -> str:
    m = _VERDICT_RE.search(text or "")
    return m.group(1) if m else ""


def _list_arg(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    try:
        items = list(value or [])
    except TypeError:
        items = [value]
    return [str(item).strip() for item in items if str(item).strip()]


def _compose_attack_payload(body: dict) -> dict:
    request = str(body.get("request") or body.get("prompt") or "").strip()
    preset_name = str(body.get("preset") or "").strip()
    transforms = _list_arg(body.get("transforms"))
    system = str(body.get("system") or "")
    try:
        max_tokens = int(body.get("max_tokens", 1024))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_tokens must be an integer") from exc

    raw_payload = body.get("payload")
    if raw_payload is not None:
        payload = str(raw_payload)
        if not payload.strip():
            raise ValueError("'payload' is required")
        return {
            "request": request,
            "prompt": payload,
            "payload": payload,
            "preset": preset_name,
            "transforms": transforms,
            "system": system,
            "max_tokens": max_tokens,
            "source": "payload",
        }

    if not request:
        raise ValueError("'request' is required")

    prompt = request
    if preset_name:
        from ..presets import get_preset

        preset = get_preset(preset_name)
        if preset is None:
            raise ValueError(f"unknown preset {preset_name}")
        prompt = preset.template.replace("{request}", request)

    unknown = [name for name in transforms if name not in TRANSFORMS]
    if unknown:
        raise ValueError(f"unknown transform(s): {', '.join(unknown)}")
    payload = apply_chain(prompt, transforms) if transforms else prompt
    return {
        "request": request,
        "prompt": prompt,
        "payload": payload,
        "preset": preset_name,
        "transforms": transforms,
        "system": system,
        "max_tokens": max_tokens,
        "source": "compose",
    }


def _apply_settings(config, prefs: dict) -> None:
    """Apply runtime overrides from a prefs dict onto the live config object: target
    (model/profile/modality/provider via state.apply_target — re-derives modality from the
    model so an image model never stays modality='text'), attacker profile + model, judge
    model. Mutates config in place so every endpoint sees the change immediately."""
    if config is None:
        return
    from ..state import apply_target

    apply_target(config, prefs)

    prof = prefs.get("profile")
    if isinstance(prof, str) and prof in config.profiles:
        config.default_profile = prof
    am = prefs.get("attacker_model")
    if isinstance(am, str) and am and config.profiles:
        cur = config.profile()
        config.profiles[config.default_profile] = dataclasses.replace(cur, model=am)
    jm = prefs.get("judge_model")
    if isinstance(jm, str) and jm:
        if config.judge is not None:
            config.judge = dataclasses.replace(config.judge, model=jm)
        elif config.profiles:
            config.judge = dataclasses.replace(config.profile(), name="judge", model=jm)


def _settings_view(config) -> dict:
    if config is None:
        return {"profiles": [], "default_profile": None, "attacker_model": None,
                "target": None, "judge_model": None}
    attacker_model = None
    if config.profiles:
        try:
            attacker_model = config.profile().model
        except Exception:
            attacker_model = None
    tgt = getattr(config, "target", None)
    target = None
    if tgt is not None:
        target = {
            "model": tgt.model, "modality": getattr(tgt, "modality", "text"),
            "base_url": tgt.base_url, "protocol": tgt.protocol,
            "provider": list(getattr(tgt, "provider", ()) or ()),
        }
    judge = getattr(config, "judge", None)
    return {
        "profiles": list(config.profiles.keys()),
        "default_profile": config.default_profile,
        "attacker_model": attacker_model,
        "target": target,
        "judge_model": getattr(judge, "model", None) if judge else None,
    }


def create_app(config=None, sessions_dir: str | Path = "sessions", web_dir: str | Path | None = None):
    """Build the Wallbreaker dashboard FastAPI app. fastapi is an optional extra
    (`pip install -e '.[dashboard]'`), imported lazily so the package imports without it."""
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles

    sessions = Path(sessions_dir)
    from ..session import RunLog, run_models_meta

    console_runlog = RunLog(directory=str(sessions))
    if config is not None:
        try:
            from ..state import load_state, state_path_for

            _apply_settings(config, load_state(state_path_for(config)))
        except Exception:
            pass
    app = FastAPI(title="Wallbreaker", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _latest():
        return report_mod.latest_run_log(sessions)

    @app.get("/api/health")
    def health():
        return {"ok": True, "name": "wallbreaker", "version": "0.1.0"}

    @app.get("/api/config")
    def config_info():
        return _config_summary(config)

    @app.get("/api/settings")
    def settings_get():
        return _settings_view(config)

    @app.post("/api/settings")
    def settings_post(body: dict):
        if config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        from ..state import load_state, save_state, state_path_for

        prefs = load_state(state_path_for(config))

        if "target_profile" in body and body["target_profile"]:
            name = str(body["target_profile"])
            if name not in config.profiles:
                raise HTTPException(status_code=400, detail=f"unknown profile '{name}'")
            prefs["target_profile"] = name
            prefs.pop("target_model", None)
        if body.get("target_model"):
            prefs["target_model"] = str(body["target_model"])
            prefs.pop("target_profile", None)
        if "target_modality" in body and body["target_modality"]:
            mod = str(body["target_modality"]).lower()
            if mod in ("text", "image"):
                prefs["target_modality"] = mod
            elif mod == "auto":
                prefs.pop("target_modality", None)
        if "target_provider" in body:
            prov = body["target_provider"]
            prefs["target_provider"] = list(prov) if isinstance(prov, list) else []
        if body.get("attacker_profile"):
            name = str(body["attacker_profile"])
            if name not in config.profiles:
                raise HTTPException(status_code=400, detail=f"unknown profile '{name}'")
            prefs["profile"] = name
            prefs.pop("attacker_model", None)
        if body.get("attacker_model"):
            prefs["attacker_model"] = str(body["attacker_model"])
        if body.get("judge_model"):
            prefs["judge_model"] = str(body["judge_model"])

        save_state(state_path_for(config), prefs)
        _apply_settings(config, prefs)
        return _settings_view(config)

    @app.get("/api/overview")
    def overview():
        log = _latest()
        scorecard = {}
        findings_count = 0
        if log is not None:
            try:
                scorecard = report_mod.build_scorecard(log)
            except Exception:
                scorecard = {}
            try:
                findings_count = len(_findings_for_run(log))
            except Exception:
                findings_count = 0
        runs = sorted(sessions.glob("run-*.jsonl")) if sessions.is_dir() else []
        return {
            "config": _config_summary(config),
            "scorecard": scorecard,
            "findings_count": findings_count,
            "runs_count": len(runs),
            "latest_run": log.name if log else None,
        }

    @app.get("/api/runs")
    def runs():
        if not sessions.is_dir():
            return []
        out = []
        for p in sorted(sessions.glob("run-*.jsonl"), reverse=True):
            try:
                records = report_mod._load_records(p)
                hits = sum(
                    1 for r in records
                    if str(r.get("label", "")).upper() in ("COMPLIED", "PARTIAL")
                )
            except Exception:
                records, hits = [], 0
            out.append({
                "name": p.name,
                "time": _run_time_from_name(p.name),
                "models": _models_from_records(records),
                "size": p.stat().st_size,
                "records": len(records),
                "hits": hits,
            })
        return out

    @app.get("/api/runs/{name}")
    def run_detail(name: str):
        path = _safe_run_path(sessions, name)
        if path is None:
            raise HTTPException(status_code=404, detail="run not found")
        records, raw_records, line_numbers = _load_records_with_lines(path)
        return {
            "name": name,
            "total": len(records),
            "records": records,
            "raw_records": raw_records,
            "line_numbers": line_numbers,
        }

    @app.get("/api/findings/runs")
    def finding_runs():
        return _finding_run_summaries(sessions)

    @app.get("/api/findings")
    def findings(runs: str | None = None):
        selected = [name.strip() for name in (runs or "").split(",") if name.strip()]
        paths = []
        if selected:
            for name in selected:
                path = _safe_run_path(sessions, name)
                if path is not None:
                    paths.append(path)
        else:
            log = _latest()
            if log is not None:
                paths.append(log)
        out = []
        for path in paths:
            try:
                out.extend(_findings_for_run(path))
            except Exception:
                continue
        out.sort(key=lambda item: (str(item.get("run", "")), int(item.get("line", 0))), reverse=True)
        return out

    @app.get("/api/scorecard")
    def scorecard():
        log = _latest()
        if log is None:
            return {}
        try:
            return report_mod.build_scorecard(log)
        except Exception:
            return {}

    @app.get("/api/presets")
    def presets():
        return [{"name": p.name, "description": p.description} for p in list_presets()]

    @app.get("/api/transforms")
    def transforms():
        return [
            {
                "name": t.name,
                "description": t.description,
                "lossy": t.lossy,
                "reversible": t.reversible,
            }
            for t in list_transforms()
        ]

    @app.get("/api/tools")
    def tools():
        if config is None:
            return []
        try:
            from ..tools import build_registry

            reg = build_registry(config)
            return [{"name": s["name"], "description": s["description"]} for s in reg.specs()]
        except Exception:
            return []

    @app.post("/api/compose")
    def compose(body: dict):
        try:
            return _compose_attack_payload(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/fire")
    async def fire(body: dict):
        if config is None or getattr(config, "target", None) is None:
            raise HTTPException(status_code=400, detail="no [target] configured in config.toml")
        try:
            composed = _compose_attack_payload(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        args = {
            "prompt": composed["payload"] if composed["source"] == "payload" else composed["prompt"],
            "max_tokens": composed["max_tokens"],
        }
        if composed["source"] != "payload" and composed["transforms"]:
            args["transforms"] = composed["transforms"]
        if composed["system"]:
            args["system"] = composed["system"]

        from ..tools import build_registry

        reg = build_registry(config)
        result = await reg.execute("query_target", args)
        verdict = _extract_verdict(result.content)
        if not console_runlog._started:
            console_runlog.set_run_meta(
                source="dashboard_console",
                models=run_models_meta(config, attacker=None),
            )
        target = getattr(config, "target", None)
        console_runlog.event(
            "attack_fire",
            request=composed["request"],
            prompt=composed["prompt"],
            payload=composed["payload"],
            response=result.content,
            label=verdict,
            technique="console",
            preset=composed["preset"],
            transforms=composed["transforms"],
            system=composed["system"],
            is_error=result.is_error,
            max_tokens=composed["max_tokens"],
            target_model=getattr(target, "model", "") if target else "",
            target_base_url=getattr(target, "base_url", "") if target else "",
        )
        return {
            **composed,
            "content": result.content,
            "response": result.content,
            "is_error": result.is_error,
            "verdict": verdict,
            "run_log": console_runlog.path.name,
        }

    agent_lock = asyncio.Lock()

    @app.post("/api/agent/run")
    async def agent_run(body: dict):
        from fastapi.responses import StreamingResponse

        if config is None or getattr(config, "target", None) is None:
            raise HTTPException(status_code=400, detail="no [target] configured in config.toml")
        try:
            brain = config.profile()
        except Exception:
            raise HTTPException(status_code=400, detail="no attacker profile configured")
        if brain is None:
            raise HTTPException(status_code=400, detail="no attacker profile configured")
        objective = str(body.get("objective") or "").strip()
        if not objective:
            raise HTTPException(status_code=400, detail="'objective' is required")
        if agent_lock.locked():
            raise HTTPException(status_code=409, detail="an agent run is already in progress")
        max_rounds = max(1, min(int(body.get("max_rounds", 8)), 20))

        from ..agent.loop import AgentEvents, run_autonomous
        from ..agent.messages import user
        from ..prompts import DEFAULT_SYSTEM
        from ..providers.factory import build_provider
        from ..session import RunLog, run_models_meta
        from ..tools import build_registry

        provider = build_provider(brain)
        registry = build_registry(config)
        runlog = RunLog(directory=str(sessions))
        runlog.set_run_meta(models=run_models_meta(config, attacker=brain))
        queue: asyncio.Queue = asyncio.Queue()

        def push(ev) -> None:
            try:
                queue.put_nowait(ev)
            except Exception:
                pass

        registry.ctx.progress = lambda m: push({"type": "progress", "text": str(m)})
        registry.ctx.record = lambda p, r, lbl, rs, t: runlog.verdict(p, r, lbl, rs, t)

        events = AgentEvents(
            on_text=lambda t: push({"type": "text", "text": t}),
            on_tool_start=lambda _i, n, a: push({"type": "tool_start", "name": n, "args": _summarize_args(a)}),
            on_tool_result=lambda _i, n, c, e: push({
                "type": "tool_result", "name": n, "content": (c or "")[:6000],
                "error": bool(e), "verdict": _extract_verdict(c or ""),
            }),
            on_round=lambda r, m: push({"type": "round", "round": r, "max": m}),
            on_error=lambda e: push({"type": "error", "error": str(e)}),
            on_feedback=lambda m: push({"type": "feedback", "text": str(m)}),
            on_usage=lambda i, o: push({"type": "usage", "input": i, "output": o}),
        )

        history = [user(objective)]
        runlog.event("objective", text=objective)

        async def runner():
            async with agent_lock:
                try:
                    res = await run_autonomous(
                        provider, registry, history, system=DEFAULT_SYSTEM,
                        events=events, max_rounds=max_rounds,
                    )
                    data = res.data or {}
                    push({
                        "type": "done", "status": res.status,
                        "summary": data.get("summary") or data.get("question") or "",
                    })
                except Exception as exc:  # noqa: BLE001
                    push({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
                finally:
                    push(None)

        task = asyncio.create_task(runner())

        async def gen():
            push({"type": "start", "objective": objective, "brain": getattr(brain, "model", ""),
                  "target": getattr(config.target, "model", "")})
            try:
                while True:
                    ev = await queue.get()
                    if ev is None:
                        break
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    dist = _web_dist(web_dir)
    if dist is not None:
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")
    else:
        @app.get("/")
        def _no_build():
            return {
                "message": "Wallbreaker dashboard API is running, but the web UI is not built.",
                "build": "cd wallbreaker/dashboard/web && npm install && npm run build",
                "api": "/api/overview",
            }

    return app


def serve(host: str = "127.0.0.1", port: int = 8787, config=None, sessions_dir="sessions"):
    import uvicorn

    app = create_app(config=config, sessions_dir=sessions_dir)
    uvicorn.run(app, host=host, port=port)
