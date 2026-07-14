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
_ENDPOINT_PREFIXES = ("attacker", "target", "judge", "art")
_ENDPOINT_FIELDS = (
    "protocol", "base_url", "model", "api_key_env", "provider", "timeout",
    "modality", "reasoning", "system_mode", "system_prompt_file", "auth_style",
    "inference_path", "models_path",
)


TYPICAL_CONFIGURATIONS = [
    {
        "id": "balanced",
        "name": "Balanced",
        "description": "Default dashboard run profile.",
        "agent": {"max_rounds": 8, "max_tokens": 8192},
        "advanced": {
            "runtime": {
                "auto": False, "rounds": 8, "no_tools": False,
                "exit_on_finish": True, "log": True, "judge": True, "resume": "",
            },
            "target": {"timeout": 90, "reasoning": False},
            "judge": {"timeout": 120, "reasoning": False},
        },
    },
    {
        "id": "fast_triage",
        "name": "Fast triage",
        "description": "Short agent runs and lower token budgets.",
        "agent": {"max_rounds": 4, "max_tokens": 4096},
        "advanced": {
            "runtime": {
                "auto": False, "rounds": 4, "no_tools": False,
                "exit_on_finish": True, "log": True, "judge": False, "resume": "",
            },
            "target": {"timeout": 30, "reasoning": False},
            "judge": {"timeout": 60, "reasoning": False},
        },
    },
    {
        "id": "deep_audit",
        "name": "Deep audit",
        "description": "Longer autonomous runs with larger response budgets.",
        "agent": {"max_rounds": 20, "max_tokens": 16000},
        "advanced": {
            "runtime": {
                "auto": True, "rounds": 20, "no_tools": False,
                "exit_on_finish": False, "log": True, "judge": True, "resume": "",
            },
            "target": {"timeout": 180, "reasoning": True},
            "judge": {"timeout": 180, "reasoning": False},
        },
    },
]


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


def _int_setting(value, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lo, min(parsed, hi))


def _agent_settings(prefs: dict | None = None) -> dict:
    prefs = prefs or {}
    return {
        "max_rounds": _int_setting(
            prefs.get("agent_max_rounds", prefs.get("rounds")),
            8,
            1,
            50,
        ),
        "max_tokens": _int_setting(
            prefs.get("agent_max_tokens"),
            8192,
            256,
            32000,
        ),
    }


def _bool_setting(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _endpoint_to_advanced(endpoint, prefs: dict, prefix: str) -> dict:
    data = {
        "protocol": getattr(endpoint, "protocol", "") if endpoint else "",
        "base_url": getattr(endpoint, "base_url", "") if endpoint else "",
        "model": getattr(endpoint, "model", "") if endpoint else "",
        "api_key_env": getattr(endpoint, "api_key_env", "") if endpoint else "",
        "provider": ",".join(getattr(endpoint, "provider", ()) or ()) if endpoint else "",
        "timeout": getattr(endpoint, "timeout", 0) if endpoint else 0,
        "modality": getattr(endpoint, "modality", "text") if endpoint else "text",
        "reasoning": bool(getattr(endpoint, "reasoning", False)) if endpoint else False,
        "system_mode": getattr(endpoint, "system_mode", "default") if endpoint else "default",
        "system_prompt_file": getattr(endpoint, "system_prompt_file", "") if endpoint else "",
        "auth_style": getattr(endpoint, "auth_style", "x-api-key") if endpoint else "x-api-key",
    }
    for field in _ENDPOINT_FIELDS:
        key = f"{prefix}_{field}"
        if key in prefs:
            data[field] = prefs[key]
    if isinstance(data.get("provider"), list):
        data["provider"] = ",".join(str(item) for item in data["provider"])
    return data


def _advanced_settings(config, prefs: dict | None = None) -> dict:
    prefs = prefs or {}
    attacker = None
    if config is not None and getattr(config, "profiles", None):
        try:
            attacker = config.profile()
        except Exception:
            attacker = None
    return {
        "runtime": {
            "auto": _bool_setting(prefs.get("auto"), False),
            "rounds": _int_setting(prefs.get("rounds"), 12, 1, 50),
            "no_tools": _bool_setting(prefs.get("no_tools"), False),
            "exit_on_finish": _bool_setting(prefs.get("exit_on_finish"), True),
            "log": _bool_setting(prefs.get("log"), True),
            "judge": _bool_setting(prefs.get("judge"), False),
            "resume": str(prefs.get("resume", "")),
        },
        "attacker": _endpoint_to_advanced(attacker, prefs, "attacker"),
        "target": _endpoint_to_advanced(getattr(config, "target", None), prefs, "target"),
        "judge": _endpoint_to_advanced(getattr(config, "judge", None), prefs, "judge"),
        "art": _endpoint_to_advanced(getattr(config, "art", None), prefs, "art"),
    }


def _parse_provider(value) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _store_advanced_settings(prefs: dict, advanced: dict) -> None:
    runtime = advanced.get("runtime") if isinstance(advanced.get("runtime"), dict) else {}
    if "auto" in runtime:
        prefs["auto"] = _bool_setting(runtime.get("auto"), False)
    if "rounds" in runtime:
        prefs["rounds"] = _int_setting(runtime.get("rounds"), 12, 1, 50)
    if "no_tools" in runtime:
        prefs["no_tools"] = _bool_setting(runtime.get("no_tools"), False)
    if "exit_on_finish" in runtime:
        prefs["exit_on_finish"] = _bool_setting(runtime.get("exit_on_finish"), True)
    if "log" in runtime:
        prefs["log"] = _bool_setting(runtime.get("log"), True)
    if "judge" in runtime:
        prefs["judge"] = _bool_setting(runtime.get("judge"), False)
    if "resume" in runtime:
        prefs["resume"] = str(runtime.get("resume") or "")

    for prefix in _ENDPOINT_PREFIXES:
        section = advanced.get(prefix)
        if not isinstance(section, dict):
            continue
        for field in _ENDPOINT_FIELDS:
            if field not in section:
                continue
            key = f"{prefix}_{field}"
            value = section[field]
            if field == "provider":
                prefs[key] = _parse_provider(value)
            elif field == "timeout":
                prefs[key] = _int_setting(value, 0, 0, 600)
            elif field == "reasoning":
                prefs[key] = _bool_setting(value, False)
            elif field == "modality":
                prefs[key] = str(value).lower() if str(value).lower() in ("text", "image", "auto") else "text"
            elif field == "system_mode":
                prefs[key] = str(value).lower() if str(value).lower() in ("default", "merge", "drop") else "default"
            elif field == "protocol":
                prefs[key] = str(value).lower() if str(value).lower() in ("openai", "anthropic", "claude-code") else ""
            elif field == "auth_style":
                prefs[key] = str(value).lower() if str(value).lower() in ("x-api-key", "bearer") else "x-api-key"
            else:
                prefs[key] = str(value or "")


def _replace_endpoint(endpoint, prefix: str, prefs: dict):
    if endpoint is None:
        return None
    updates = {}
    for field in _ENDPOINT_FIELDS:
        key = f"{prefix}_{field}"
        if key not in prefs:
            continue
        value = prefs[key]
        if field == "provider":
            updates[field] = tuple(_parse_provider(value))
        elif field == "timeout":
            updates[field] = float(_int_setting(value, 0, 0, 600))
        elif field == "reasoning":
            updates[field] = _bool_setting(value, False)
        elif field == "modality":
            mod = str(value).lower()
            if mod in ("text", "image"):
                updates[field] = mod
        elif field == "protocol":
            protocol = str(value).lower()
            if protocol in ("openai", "anthropic", "claude-code"):
                updates[field] = protocol
        elif field == "system_mode":
            mode = str(value).lower()
            if mode in ("default", "merge", "drop"):
                updates[field] = mode
        elif field == "auth_style":
            auth_style = str(value).lower()
            if auth_style in ("x-api-key", "bearer"):
                updates[field] = auth_style
        else:
            updates[field] = str(value or "").rstrip("/") if field == "base_url" else str(value or "")
    return dataclasses.replace(endpoint, **updates) if updates else endpoint


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
    if config.profiles:
        cur = config.profile()
        config.profiles[config.default_profile] = _replace_endpoint(cur, "attacker", prefs)
    judge_profile = prefs.get("judge_profile")
    if isinstance(judge_profile, str) and judge_profile in config.profiles:
        source = config.profiles[judge_profile]
        config.judge = dataclasses.replace(source, name="judge")
        if hasattr(source, "_catalog_path"):
            config.judge._catalog_path = source._catalog_path
            config.judge._provider_id = judge_profile
    jm = prefs.get("judge_model")
    if isinstance(jm, str) and jm:
        if config.judge is not None:
            config.judge = dataclasses.replace(config.judge, model=jm)
        elif config.profiles:
            config.judge = dataclasses.replace(config.profile(), name="judge", model=jm)
    if config.target is not None:
        config.target = _replace_endpoint(config.target, "target", prefs)
    if config.judge is not None:
        config.judge = _replace_endpoint(config.judge, "judge", prefs)
    if config.art is not None:
        config.art = _replace_endpoint(config.art, "art", prefs)


def _settings_view(config, prefs: dict | None = None) -> dict:
    agent = _agent_settings(prefs)
    if config is None:
        return {"profiles": [], "default_profile": None, "attacker_model": None,
                "target": None, "judge_model": None, "agent": agent,
                "profile_details": {},
                "advanced": _advanced_settings(None, prefs),
                "typical_configurations": TYPICAL_CONFIGURATIONS}
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
        "profile_details": {
            name: {
                "name": name,
                "model": endpoint.model,
                "protocol": endpoint.protocol,
                "base_url": endpoint.base_url,
                "modality": getattr(endpoint, "modality", "text"),
            }
            for name, endpoint in config.profiles.items()
        },
        "default_profile": config.default_profile,
        "attacker_model": attacker_model,
        "target": target,
        "target_profile": prefs.get("target_profile") if isinstance(prefs.get("target_profile"), str) else None,
        "judge_model": getattr(judge, "model", None) if judge else None,
        "judge_profile": prefs.get("judge_profile") if isinstance(prefs.get("judge_profile"), str) else None,
        "agent": agent,
        "advanced": _advanced_settings(config, prefs),
        "typical_configurations": TYPICAL_CONFIGURATIONS,
    }


def _model_ids(payload) -> list[str]:
    """Normalize OpenAI/Anthropic-compatible model-list response shapes."""
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("data", payload.get("models", []))
    if not isinstance(rows, list):
        return []
    models = []
    for row in rows:
        model_id = row.get("id") or row.get("name") if isinstance(row, dict) else row
        if model_id and str(model_id).strip():
            models.append(str(model_id).strip())
    return sorted(set(models), key=str.casefold)


async def _discover_profile_models(profile: str, endpoint) -> dict:
    current = str(getattr(endpoint, "model", "") or "").strip()
    fallback = [current] if current else []
    protocol = str(getattr(endpoint, "protocol", "") or "").lower()
    base_url = str(getattr(endpoint, "base_url", "") or "").rstrip("/")
    result = {
        "profile": profile,
        "protocol": protocol,
        "models": fallback,
        "fetched": False,
        "error": "",
    }
    if protocol == "claude-code":
        result["error"] = "This local provider does not expose a model catalog."
        return result
    if not base_url:
        result["error"] = "This profile has no model catalog URL."
        return result

    import httpx

    custom_path = str(getattr(endpoint, "models_path", "") or "")
    if protocol == "anthropic":
        path = custom_path or "/v1/models"
        url = f"{base_url}{path if path.startswith('/') else '/' + path}"
        headers = {
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        key = endpoint.resolved_key()
        if key:
            if getattr(endpoint, "auth_style", "x-api-key") == "bearer":
                headers["Authorization"] = f"Bearer {key}"
            else:
                headers["x-api-key"] = key
    else:
        path = custom_path or "/models"
        url = f"{base_url}{path if path.startswith('/') else '/' + path}"
        headers = {"Content-Type": "application/json"}
        key = endpoint.resolved_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            models = _model_ids(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        result["error"] = f"Model catalog unavailable: {exc}"
        return result

    if current and current not in models:
        models.append(current)
        models.sort(key=str.casefold)
    result["models"] = models
    result["fetched"] = True
    return result


def create_app(config=None, sessions_dir: str | Path = "sessions", web_dir: str | Path | None = None):
    """Build the Wallbreaker dashboard FastAPI app. fastapi is an optional extra
    (`pip install -e '.[dashboard]'`), imported lazily so the package imports without it."""
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles

    sessions = Path(sessions_dir)
    from ..session import RunLog, run_models_meta

    console_runlog = RunLog(directory=str(sessions))
    provider_registry = None
    model_catalog = None
    if config is not None:
        try:
            from ..provider_registry import ProviderRegistry

            provider_registry = ProviderRegistry(config)
            from ..model_catalog import ModelCatalog, catalog_path_for

            model_catalog = ModelCatalog(catalog_path_for(config))
            for provider_id, endpoint in config.profiles.items():
                model_catalog.upsert(provider_id, endpoint.model, "configured")
            from ..state import load_state, state_path_for

            _apply_settings(config, load_state(state_path_for(config)))
        except Exception:
            pass
    app = FastAPI(title="Wallbreaker", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
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
        prefs = {}
        if config is not None:
            try:
                from ..state import load_state, state_path_for

                prefs = load_state(state_path_for(config))
            except Exception:
                prefs = {}
        return _settings_view(config, prefs)

    @app.get("/api/providers")
    def providers_get():
        return provider_registry.list() if provider_registry is not None else []

    @app.get("/api/providers/{name}")
    def provider_get(name: str):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        item = provider_registry.get(name)
        if item is None:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        return item

    @app.put("/api/providers/{name}")
    def provider_put(name: str, body: dict):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            return provider_registry.save(name, body)
        except Exception as exc:
            from ..config import ConfigError

            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise

    @app.delete("/api/providers/{name}")
    def provider_delete(name: str):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            provider_registry.delete(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'") from exc
        return {"ok": True}

    @app.post("/api/providers/{name}/reset")
    def provider_reset(name: str):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            return provider_registry.reset(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"provider '{name}' has no config baseline") from exc

    @app.post("/api/providers/{name}/test")
    async def provider_test(name: str):
        if config is None or name not in config.profiles:
            raise HTTPException(status_code=404, detail=f"unknown or disabled provider '{name}'")
        result = await _discover_profile_models(name, config.profiles[name])
        return {"ok": bool(result["fetched"]), **result}

    @app.get("/api/provider-spec/drafts")
    def provider_spec_drafts():
        return provider_registry.list_drafts() if provider_registry is not None else []

    @app.get("/api/provider-spec/drafts/{draft_id}")
    def provider_spec_draft_get(draft_id: str):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        draft = provider_registry.get_draft(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="unknown provider specification draft")
        return draft

    @app.put("/api/provider-spec/drafts/{draft_id}")
    def provider_spec_draft_put(draft_id: str, body: dict):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            return provider_registry.update_draft(draft_id, body)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown provider specification draft") from exc

    @app.delete("/api/provider-spec/drafts/{draft_id}")
    def provider_spec_draft_delete(draft_id: str):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            provider_registry.discard_draft(draft_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown provider specification draft") from exc
        return {"ok": True}

    @app.post("/api/provider-spec/drafts/{draft_id}/apply")
    def provider_spec_draft_apply(draft_id: str):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            provider = provider_registry.apply_draft(draft_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown provider specification draft") from exc
        except Exception as exc:
            from ..config import ConfigError

            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise
        if model_catalog is not None:
            model_catalog.upsert(provider["name"], provider["model"], "configured")
        return provider

    def _roles_view(prefs: dict) -> dict:
        roles = {}
        role_keys = {
            "attacker": ("profile", "attacker_model"),
            "target": ("target_profile", "target_model"),
            "judge": ("judge_profile", "judge_model"),
            "research": ("research_profile", "research_model"),
        }
        for role, (profile_key, model_key) in role_keys.items():
            profile = prefs.get(profile_key)
            if not isinstance(profile, str) or profile not in getattr(config, "profiles", {}):
                profile = getattr(config, "default_profile", None)
            endpoint = config.profiles.get(profile) if config is not None and profile else None
            model = prefs.get(model_key) or getattr(endpoint, "model", "")
            if role == "target" and getattr(config, "target", None) is not None:
                model = prefs.get(model_key) or config.target.model
            if role == "judge" and getattr(config, "judge", None) is not None:
                model = prefs.get(model_key) or config.judge.model
            roles[role] = {"provider": profile, "model": model}
        roles["research"]["max_rounds"] = _int_setting(prefs.get("research_agent_max_rounds"), 6, 1, 20)
        roles["research"]["max_tokens"] = _int_setting(prefs.get("research_agent_max_tokens"), 8192, 256, 32000)
        return roles

    @app.get("/api/roles")
    def roles_get():
        if config is None:
            return {}
        from ..state import load_state, state_path_for

        return _roles_view(load_state(state_path_for(config)))

    @app.put("/api/roles/{role}")
    def role_put(role: str, body: dict):
        if config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        keys = {
            "attacker": ("profile", "attacker_model"),
            "target": ("target_profile", "target_model"),
            "judge": ("judge_profile", "judge_model"),
            "research": ("research_profile", "research_model"),
        }
        if role not in keys:
            raise HTTPException(status_code=404, detail=f"unknown role '{role}'")
        provider = str(body.get("provider") or "")
        model = str(body.get("model") or "").strip()
        if provider not in config.profiles:
            raise HTTPException(status_code=400, detail=f"unknown provider '{provider}'")
        if not model:
            raise HTTPException(status_code=400, detail="model is required")
        from ..state import load_state, save_state, state_path_for

        path = state_path_for(config)
        prefs = load_state(path)
        provider_key, model_key = keys[role]
        prefs[provider_key] = provider
        prefs[model_key] = model
        if role == "research":
            prefs["research_agent_max_rounds"] = _int_setting(body.get("max_rounds"), 6, 1, 20)
            prefs["research_agent_max_tokens"] = _int_setting(body.get("max_tokens"), 8192, 256, 32000)
        save_state(path, prefs)
        _apply_settings(config, prefs)
        return _roles_view(prefs)[role]

    research_lock = asyncio.Lock()

    @app.post("/api/provider-spec/discover")
    async def provider_spec_discover(body: dict):
        from fastapi.responses import StreamingResponse

        if config is None or provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        provider_name = str(body.get("provider_name") or "").strip()
        if not provider_name:
            raise HTTPException(status_code=400, detail="provider_name is required")
        if research_lock.locked():
            raise HTTPException(status_code=409, detail="provider research is already in progress")
        from ..state import load_state, state_path_for

        prefs = load_state(state_path_for(config))
        profile = str(body.get("research_provider") or prefs.get("research_profile") or config.default_profile)
        if profile not in config.profiles:
            raise HTTPException(status_code=400, detail=f"unknown research provider '{profile}'")
        model = str(body.get("research_model") or prefs.get("research_model") or config.profiles[profile].model)
        research_endpoint = dataclasses.replace(config.profiles[profile], model=model)
        if hasattr(config.profiles[profile], "_catalog_path"):
            research_endpoint._catalog_path = config.profiles[profile]._catalog_path
            research_endpoint._provider_id = profile
        from ..provider_research import ProviderSpecAgent
        from ..providers.factory import build_provider

        agent = ProviderSpecAgent(build_provider(research_endpoint), config)
        queue: asyncio.Queue = asyncio.Queue()

        def push(event):
            queue.put_nowait(event)

        async def runner():
            async with research_lock:
                try:
                    draft = await agent.run(
                        provider_name=provider_name,
                        docs_urls=_list_arg(body.get("docs_urls")),
                        spec_text=str(body.get("spec_text") or ""),
                        notes=str(body.get("notes") or ""),
                        max_rounds=_int_setting(body.get("max_rounds"), prefs.get("research_agent_max_rounds", 6), 1, 20),
                        max_tokens=_int_setting(body.get("max_tokens"), prefs.get("research_agent_max_tokens", 8192), 256, 32000),
                        emit=push,
                    )
                    saved = provider_registry.save_draft(draft)
                    push({"type": "done", "draft": saved})
                except Exception as exc:  # noqa: BLE001
                    push({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
                finally:
                    push(None)

        task = asyncio.create_task(runner())

        async def stream():
            push({"type": "start", "provider_name": provider_name, "research_provider": profile, "research_model": model})
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        })

    @app.get("/api/models")
    async def models_get(profile: str):
        if config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        if profile not in config.profiles:
            raise HTTPException(status_code=404, detail=f"unknown profile '{profile}'")
        result = await _discover_profile_models(profile, config.profiles[profile])
        if model_catalog is not None:
            if result["fetched"]:
                model_catalog.sync(profile, result["models"], "remote")
            entries = model_catalog.list(profile)
            result["entries"] = entries
            result["models"] = [entry["model_id"] for entry in entries]
        return result

    @app.get("/api/providers/{name}/models")
    def provider_models(name: str):
        if config is None or name not in config.profiles:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        entries = model_catalog.list(name) if model_catalog is not None else []
        return {"provider": name, "models": [item["model_id"] for item in entries], "entries": entries}

    @app.post("/api/providers/{name}/models")
    def provider_model_add(name: str, body: dict):
        if config is None or name not in config.profiles:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        model_id = str(body.get("model") or "").strip()
        if not model_id:
            raise HTTPException(status_code=400, detail="model is required")
        model_catalog.upsert(name, model_id, "manual")
        return {"provider": name, "model": model_id, "entries": model_catalog.list(name)}

    @app.post("/api/providers/{name}/models/refresh")
    async def provider_models_refresh(name: str):
        if config is None or name not in config.profiles:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        result = await _discover_profile_models(name, config.profiles[name])
        if result["fetched"]:
            model_catalog.sync(name, result["models"], "remote")
        result["entries"] = model_catalog.list(name)
        result["models"] = [item["model_id"] for item in result["entries"]]
        return result

    @app.post("/api/settings")
    def settings_post(body: dict):
        if config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        from ..state import load_state, save_state, state_path_for

        prefs = load_state(state_path_for(config))

        has_target_profile = bool(body.get("target_profile"))
        has_target_model = bool(body.get("target_model"))
        if has_target_profile:
            name = str(body["target_profile"])
            if name not in config.profiles:
                raise HTTPException(status_code=400, detail=f"unknown profile '{name}'")
            prefs["target_profile"] = name
            if not has_target_model:
                prefs.pop("target_model", None)
        if has_target_model:
            prefs["target_model"] = str(body["target_model"])
            if not has_target_profile:
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
        has_judge_profile = bool(body.get("judge_profile"))
        has_judge_model = bool(body.get("judge_model"))
        if has_judge_profile:
            name = str(body["judge_profile"])
            if name not in config.profiles:
                raise HTTPException(status_code=400, detail=f"unknown profile '{name}'")
            prefs["judge_profile"] = name
            if not has_judge_model:
                prefs.pop("judge_model", None)
        if has_judge_model:
            prefs["judge_model"] = str(body["judge_model"])
            if not has_judge_profile:
                prefs.pop("judge_profile", None)
        agent = body.get("agent") if isinstance(body.get("agent"), dict) else body
        if "agent_max_rounds" in agent:
            prefs["agent_max_rounds"] = _int_setting(agent.get("agent_max_rounds"), 8, 1, 50)
        if "max_rounds" in agent:
            prefs["agent_max_rounds"] = _int_setting(agent.get("max_rounds"), 8, 1, 50)
        if "agent_max_tokens" in agent:
            prefs["agent_max_tokens"] = _int_setting(agent.get("agent_max_tokens"), 8192, 256, 32000)
        if "max_tokens" in agent:
            prefs["agent_max_tokens"] = _int_setting(agent.get("max_tokens"), 8192, 256, 32000)
        if isinstance(body.get("advanced"), dict):
            _store_advanced_settings(prefs, body["advanced"])
        if body.get("typical_configuration"):
            preset_id = str(body.get("typical_configuration"))
            preset = next((item for item in TYPICAL_CONFIGURATIONS if item["id"] == preset_id), None)
            if preset is None:
                raise HTTPException(status_code=400, detail=f"unknown configuration '{preset_id}'")
            prefs["agent_max_rounds"] = preset["agent"]["max_rounds"]
            prefs["agent_max_tokens"] = preset["agent"]["max_tokens"]
            _store_advanced_settings(prefs, preset["advanced"])

        save_state(state_path_for(config), prefs)
        _apply_settings(config, prefs)
        return _settings_view(config, prefs)

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
        prefs = {}
        try:
            from ..state import load_state, state_path_for

            prefs = load_state(state_path_for(config))
        except Exception:
            prefs = {}
        agent_defaults = _agent_settings(prefs)
        max_rounds = _int_setting(body.get("max_rounds"), agent_defaults["max_rounds"], 1, 50)
        max_tokens = _int_setting(body.get("max_tokens"), agent_defaults["max_tokens"], 256, 32000)

        from ..agent.loop import AgentEvents, run_autonomous
        from ..agent.messages import user
        from ..prompts import DEFAULT_SYSTEM
        from ..providers.factory import build_provider
        from ..session import RunLog, run_models_meta
        from ..tools import build_registry

        provider = build_provider(brain)
        registry = build_registry(config)
        runlog = RunLog(directory=str(sessions))
        runlog.set_run_meta(
            models=run_models_meta(config, attacker=brain),
            agent={"max_rounds": max_rounds, "max_tokens": max_tokens},
        )
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
                        events=events, max_rounds=max_rounds, max_tokens=max_tokens,
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
                  "target": getattr(config.target, "model", ""),
                  "max_rounds": max_rounds, "max_tokens": max_tokens})
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
