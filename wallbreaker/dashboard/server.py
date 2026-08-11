from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

from .. import report as report_mod
from ..agent.messages import user
from ..presets import list_presets
from ..providers.factory import build_provider
from ..transforms import TRANSFORMS, apply_chain, list_transforms
from ..session import normalize_inference_records

_log = logging.getLogger(__name__)

_VERDICT_RE = re.compile(r"\b(COMPLIED|PARTIAL|REFUSED|EMPTY|BLOCKED_INPUT|BLOCKED_OUTPUT)\b")
_RUN_NAME_RE = re.compile(r"^run-(\d{8})-?(\d{6})(?:-[^.]+)?\.jsonl$")
_FIRE_TOOLS = {"query_target", "continue_target", "fire", "query_image_target"}
_FINDING_KINDS = {"verdict", "attack_fire"}
_FINDING_LABELS = {"COMPLIED", "PARTIAL"}
_ENDPOINT_PREFIXES = ("attacker", "target", "judge", "art")
_ENDPOINT_FIELDS = (
    "protocol", "base_url", "model", "api_key_env", "provider", "timeout",
    "modality", "reasoning", "system_mode", "system_prompt_file", "auth_style",
    "inference_path", "models_path",
)
_AGENT_CONTROL_TOOLS = {"finish", "ask_operator"}

try:
    from pydantic import BaseModel, ConfigDict

    class AgentRunRequest(BaseModel):
        model_config = ConfigDict(extra="ignore")
        objective: str
        max_rounds: int | None = None
        max_tokens: int | None = None
        concurrency: int | None = None
        request_delay_ms: int | None = None
        enabled_techniques: list[str] | None = None
        run_timeout_s: int | None = None
except ImportError:  # pragma: no cover - dashboard extra supplies pydantic
    AgentRunRequest = dict


class _LiveAttackerProvider:
    """Hot-swap the attacker while preserving one autonomous conversation."""

    def __init__(self, provider, endpoint, system_builder):
        self._provider = provider
        self.endpoint = endpoint
        self._system_builder = system_builder

    @property
    def model(self) -> str:
        return self.endpoint.model

    def switch(self, provider, endpoint) -> None:
        old = self._provider
        aclose = getattr(old, "aclose", None)
        if aclose is not None and old is not provider:
            try:
                asyncio.get_running_loop().create_task(aclose())
            except Exception:
                pass
        self._provider = provider
        self.endpoint = endpoint

    async def aclose(self) -> None:
        aclose = getattr(self._provider, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                pass

    async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
        provider = self._provider
        active_system = self._system_builder(self.endpoint)
        async for event in provider.stream(
            messages,
            tools=tools,
            system=active_system,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield event


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
    found = {"attacker": "", "target": "", "judge": ""}

    def merge(value) -> None:
        if not isinstance(value, dict):
            return
        for role in found:
            model = value.get(role)
            if isinstance(model, dict):
                model = model.get("model")
            if model and not found[role]:
                found[role] = str(model)

    for record in records:
        merge(record.get("models"))
        merge(record.get("agent_roles"))
        for role in found:
            model = record.get(f"{role}_model")
            if model and not found[role]:
                found[role] = str(model)

        request = record.get("request") if isinstance(record.get("request"), dict) else {}
        endpoint = request.get("endpoint") if isinstance(request.get("endpoint"), dict) else {}
        if not endpoint and isinstance(record.get("endpoint"), dict):
            endpoint = record["endpoint"]
        name = str(endpoint.get("name") or "").lower()
        model = endpoint.get("model")
        role = next((item for item in found if item in name), "")
        if role and model and not found[role]:
            found[role] = str(model)

    return {**found, "recorded": any(found.values())}


def _models_for_finding(record: dict, run_models: dict) -> dict:
    """Prefer model attribution recorded on the finding over run-level defaults."""
    models = {role: str(run_models.get(role) or "") for role in ("attacker", "target", "judge")}
    explicit = record.get("models") if isinstance(record.get("models"), dict) else {}
    for role in models:
        value = record.get(f"{role}_model") or explicit.get(role)
        if isinstance(value, dict):
            value = value.get("model")
        if value:
            models[role] = str(value)
    return {**models, "recorded": any(models.values())}


def _safe_run_path(sessions: Path, name: str) -> Path | None:
    if ".." in name or "/" in name or "\\" in name or name in ("", ".", ".."):
        return None
    candidate = sessions / name
    if not candidate.is_file() and not Path(name).suffix:
        candidate = sessions / f"{name}.jsonl"
    if not candidate.is_file():
        return None
    base = os.path.realpath(sessions)
    resolved = os.path.realpath(candidate)
    if resolved != base and not resolved.startswith(base + os.sep):
        return None
    path = Path(resolved)
    if path.is_file():
        return path
    return None


def _reserve_runlog_path(runlog, reserved: set[Path]):
    """Give a not-yet-started RunLog a path unique to this dashboard process."""
    original = runlog.path
    candidate = original
    suffix = 1
    while candidate in reserved or candidate.exists():
        candidate = original.with_name(f"{original.stem}-{suffix:02d}{original.suffix}")
        suffix += 1
    runlog.path = candidate
    reserved.add(candidate)
    return runlog


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
        finding["models"] = _models_for_finding(record, models)
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
    display_config = config
    roles = {}
    try:
        from ..agent_profiles import resolved_config
        display_config, roles = resolved_config(config)
    except Exception:
        pass
    target = getattr(display_config, "target", None)
    judge = getattr(display_config, "judge", None)
    prof = None
    try:
        prof = roles.get("attacker", {}).get("provider", display_config.default_profile)
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
    except (TypeError, ValueError, OverflowError):
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
            1,
            32000,
        ),
        "concurrency": _int_setting(
            prefs.get("agent_concurrency"),
            3,
            1,
            32,
        ),
        "request_delay_ms": _int_setting(
            prefs.get("agent_request_delay_ms"),
            250,
            0,
            60000,
        ),
    }


def _target_settings(config, prefs: dict | None = None) -> dict:
    prefs = prefs or {}
    target = getattr(config, "target", None) if config is not None else None
    mode = str(prefs.get("target_modality", "auto")).lower()
    if mode not in ("auto", "text", "image"):
        mode = "auto"
    system_mode = str(
        prefs.get("target_system_mode", getattr(target, "system_mode", "default"))
    ).lower()
    if system_mode not in ("default", "merge", "drop"):
        system_mode = "default"
    providers = prefs.get("target_provider")
    if providers is None:
        providers = list(getattr(target, "provider", ()) or ())
    return {
        "modality": mode,
        "system_mode": system_mode,
        "provider": ", ".join(_list_arg(providers)),
        "judge_enabled": bool(prefs.get("judge", True)),
    }


def _apply_target_settings(run_config, prefs: dict | None = None, source_config=None):
    """Apply dashboard target controls to a per-run resolved config."""
    if run_config is None or run_config.target is None:
        return run_config
    from ..config import resolve_target_modality

    settings = _target_settings(source_config or run_config, prefs)
    explicit = settings["modality"] if settings["modality"] != "auto" else None
    target = dataclasses.replace(
        run_config.target,
        modality=resolve_target_modality(run_config.target.model, explicit),
        system_mode=settings["system_mode"],
        provider=tuple(_list_arg(settings["provider"])),
    )
    configured = dataclasses.replace(run_config, target=target)
    configured.judge_enabled = settings["judge_enabled"]
    return configured

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


def _settings_view(config, prefs: dict | None = None) -> dict:
    agent = _agent_settings(prefs)
    if config is None:
        return {"profiles": [], "default_profile": None, "attacker_model": None,
                "target": None, "judge_model": None, "agent": agent,
                "profile_details": {},
                "target_options": _target_settings(None, prefs)}
    display_config = config
    role_view = {}
    try:
        from ..agent_profiles import resolved_config
        display_config, role_view = resolved_config(config)
    except Exception:
        pass
    attacker_model = None
    if config.profiles:
        try:
            attacker_model = display_config.profile().model
        except Exception:
            attacker_model = None
    tgt = getattr(display_config, "target", None)
    target = None
    if tgt is not None:
        target = {
            "model": tgt.model, "modality": getattr(tgt, "modality", "text"),
            "base_url": tgt.base_url, "protocol": tgt.protocol,
            "provider": list(getattr(tgt, "provider", ()) or ()),
        }
    judge = getattr(display_config, "judge", None)
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
        "default_profile": role_view.get("attacker", {}).get("provider", config.default_profile),
        "attacker_model": attacker_model,
        "target": target,
        "target_profile": role_view.get("target", {}).get("provider"),
        "judge_model": getattr(judge, "model", None) if judge else None,
        "judge_profile": role_view.get("judge", {}).get("provider"),
        "agent": agent,
        "target_options": _target_settings(config, prefs),
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

    # SSRF guard: model discovery attaches the operator's API key to a request against a
    # profile-supplied base_url. Block private/loopback/metadata targets so a poisoned base_url
    # can't turn discovery into key exfiltration / internal probing (audit SEC-4).
    from ..tools.egress_guard import EgressBlocked, check_url, make_pinned_transport
    try:
        check_url(url)
    except EgressBlocked as exc:
        result["error"] = f"Model catalog host not allowed: {exc}"
        return result

    result["url"] = url
    try:
        # The pre-flight check above is advisory only.  Model discovery is especially
        # sensitive because it attaches an operator API key, so its socket must use the
        # same enforcing, DNS-rebind-pinned transport as the http_request tool.
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=False,
            transport=make_pinned_transport(),
        ) as client:
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


def create_app(
    config=None,
    sessions_dir: str | Path = "sessions",
    web_dir: str | Path | None = None,
    *,
    require_auth: bool = True,
    auth_token: str | None = None,
    allow_host_tools: bool = False,
):
    """Build the Wallbreaker dashboard FastAPI app. fastapi is an optional extra
    (`pip install -e '.[dashboard]'`), imported lazily so the package imports without it."""
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles

    sessions = Path(sessions_dir)
    from ..session import RunLog, run_models_meta

    # RunLog's canonical name has second-level precision. V2 can start multiple
    # background executions in that window, so reserve distinct paths before
    # any of them writes; otherwise independent runs append into one JSONL file.
    reserved_run_paths: set[Path] = set()

    def _new_dashboard_runlog() -> RunLog:
        return _reserve_runlog_path(
            RunLog(directory=str(sessions)), reserved_run_paths
        )

    console_runlog = _new_dashboard_runlog()
    console_conversation = {
        "runlog": console_runlog,
        "registry": None,
        "run_config": None,
        "role_meta": {},
        "turns": [],
    }
    provider_registry = None
    model_catalog = None
    agent_profile_registry = None
    if config is not None:
        try:
            from ..provider_registry import ProviderRegistry

            provider_registry = ProviderRegistry(config)
            from ..agent_profiles import AgentProfileRegistry
            agent_profile_registry = AgentProfileRegistry(config)
            from ..model_catalog import ModelCatalog, catalog_path_for

            model_catalog = ModelCatalog(catalog_path_for(config))
            for provider_id, endpoint in config.profiles.items():
                model_catalog.upsert(provider_id, endpoint.model, "configured")
            from ..state import load_state, save_state, state_path_for

            state_path = state_path_for(config)
            prefs = load_state(state_path)
            obsolete_keys = {
                "research_profile", "research_model",
                "research_agent_max_rounds", "research_agent_max_tokens",
                "profile", "target_profile", "judge_profile",
            }
            obsolete_keys.update(
                f"{prefix}_{field}" for prefix in _ENDPOINT_PREFIXES for field in _ENDPOINT_FIELDS
            )
            # These are current run-scoped target controls, not legacy endpoint copies.
            obsolete_keys.difference_update({
                "target_provider", "target_modality", "target_system_mode",
            })
            if obsolete_keys.intersection(prefs):
                prefs = {key: value for key, value in prefs.items() if key not in obsolete_keys}
                save_state(state_path, prefs)
            from ..providers.request_gate import configure_request_gate

            gate = _agent_settings(prefs)
            configure_request_gate(gate["concurrency"], gate["request_delay_ms"])
        except Exception as exc:
            _log.warning("dashboard init degraded — %s: %s", type(exc).__name__, exc)
    app = FastAPI(title="Wallbreaker", version="0.1.0")
    from ..executions import ExecutionManager, TERMINAL_STATES
    from ..history_index import HistoryIndex

    execution_manager = ExecutionManager()
    history_index = HistoryIndex(sessions / ".wallbreaker_history.sqlite3")
    history_index.update(sessions)
    app.state.execution_manager = execution_manager
    app.state.history_index = history_index
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    from .auth import SecurityMiddleware, TOKEN_HEADER

    token = auth_token or (__import__("secrets").token_urlsafe(32) if require_auth else "")
    app.state.auth_token = token
    app.state.require_auth = require_auth
    app.state.allow_host_tools = allow_host_tools
    app.add_middleware(SecurityMiddleware, token=token, require_auth=require_auth)

    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def _generic_500(request, exc):
        _log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    def _latest():
        return report_mod.latest_run_log(sessions)

    @app.get("/api/health")
    def health():
        return {"ok": True, "name": "wallbreaker", "version": "0.1.0"}

    @app.get("/api/session")
    def session_bootstrap(origin: str | None = Header(default=None)):
        from .auth import origin_is_same_site

        if require_auth and not origin_is_same_site(origin):
            raise HTTPException(status_code=403, detail="cross-site request blocked")
        return {
            "authenticated": bool(require_auth),
            "tokenHeader": TOKEN_HEADER,
            "token": token if require_auth else "",
        }

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
        except Exception as exc:
            from ..config import ConfigError

            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise
        return {"ok": True}

    @app.post("/api/providers/{name}/test")
    async def provider_test(name: str):
        endpoint = getattr(config, "all_profiles", {}).get(name) if config is not None else None
        if endpoint is None:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        catalog = await _discover_profile_models(name, endpoint)
        model = str(getattr(endpoint, "model", "") or "").strip()
        if not model:
            for assignment in _roles_view().values():
                if assignment.get("provider") == name and assignment.get("model"):
                    model = str(assignment["model"])
                    break
        if not model and catalog["models"]:
            model = str(catalog["models"][0])
        if not model:
            raise HTTPException(
                status_code=400,
                detail=f"Provider '{name}' has no model configured to test.",
            )

        test_endpoint = dataclasses.replace(
            endpoint,
            model=model,
            timeout=max(5.0, min(float(getattr(endpoint, "timeout", 0) or 30), 30.0)),
        )
        provider = None
        started = time.monotonic()
        try:
            provider = build_provider(test_endpoint, timeout=30)
            prompt = user("Connectivity check. Reply with OK.")
            if getattr(test_endpoint, "modality", "text") == "image":
                result = await provider.generate([prompt], max_tokens=16)
                preview = f"Generated {len(result.images)} image(s)"
                test_kind = "image_generation"
            else:
                response = await provider.complete([prompt], max_tokens=32)
                preview = response.strip().replace("\n", " ")[:160]
                test_kind = "completion"
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            secret = str(endpoint.resolved_key() or "")
            if secret:
                detail = detail.replace(secret, "[redacted]")
            raise HTTPException(
                status_code=502,
                detail=f"Authenticated inference failed for '{name}' using '{model}': {detail}",
            ) from exc
        finally:
            if provider is not None:
                await provider.aclose()

        if catalog["fetched"] and model_catalog is not None:
            model_catalog.sync(name, catalog["models"], "remote")
            catalog["refreshed_at"] = model_catalog.mark_refreshed(name)
        return {
            "ok": True,
            **catalog,
            "model": model,
            "inference": {
                "ok": True,
                "kind": test_kind,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "response_preview": preview,
            },
        }

    def _roles_view() -> dict:
        if agent_profile_registry is None:
            return {}
        return {role: data["active"] for role, data in agent_profile_registry.view()["roles"].items()}

    @app.get("/api/roles")
    def roles_get():
        if config is None:
            return {}
        return _roles_view()

    @app.put("/api/roles/{role}")
    def role_put(role: str, body: dict):
        if config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        if agent_profile_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        if role not in ("attacker", "target", "judge"):
            raise HTTPException(status_code=404, detail=f"unknown role '{role}'")
        try:
            return agent_profile_registry.activate(role, body)
        except Exception as exc:
            from ..config import ConfigError
            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise

    @app.get("/api/agent-profiles")
    def agent_profiles_get():
        return agent_profile_registry.view() if agent_profile_registry is not None else {"roles": {}}

    @app.put("/api/agent-profiles/{role}/{name}")
    def agent_profile_put(role: str, name: str, body: dict):
        if agent_profile_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            return dataclasses.asdict(agent_profile_registry.save(role, name, body))
        except Exception as exc:
            from ..config import ConfigError
            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise

    @app.delete("/api/agent-profiles/{role}/{name}")
    def agent_profile_delete(role: str, name: str):
        if agent_profile_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            agent_profile_registry.delete(role, name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown agent profile") from exc
        except Exception as exc:
            from ..config import ConfigError
            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise
        return {"ok": True}

    @app.get("/api/models")
    async def models_get(profile: str):
        if config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        endpoint = config.all_profiles.get(profile)
        if endpoint is None:
            raise HTTPException(status_code=404, detail=f"unknown profile '{profile}'")
        refreshed_at = model_catalog.last_refreshed(profile) if model_catalog is not None else ""
        if refreshed_at:
            entries = model_catalog.list(profile)
            return {
                "profile": profile,
                "protocol": endpoint.protocol,
                "models": [entry["model_id"] for entry in entries],
                "entries": entries,
                "fetched": True,
                "cached": True,
                "refreshed_at": refreshed_at,
                "error": "",
            }
        result = await _discover_profile_models(profile, endpoint)
        if model_catalog is not None:
            if result["fetched"]:
                model_catalog.sync(profile, result["models"], "remote")
                result["refreshed_at"] = model_catalog.mark_refreshed(profile)
            entries = model_catalog.list(profile)
            result["entries"] = entries
            result["models"] = [entry["model_id"] for entry in entries]
        return result

    @app.get("/api/providers/{name}/models")
    def provider_models(name: str):
        if config is None or name not in config.all_profiles:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        entries = model_catalog.list(name) if model_catalog is not None else []
        return {"provider": name, "models": [item["model_id"] for item in entries], "entries": entries}

    @app.post("/api/providers/{name}/models")
    def provider_model_add(name: str, body: dict):
        if config is None or name not in config.all_profiles:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        model_id = str(body.get("model") or "").strip()
        if not model_id:
            raise HTTPException(status_code=400, detail="model is required")
        model_catalog.upsert(name, model_id, "manual")
        return {"provider": name, "model": model_id, "entries": model_catalog.list(name)}

    @app.post("/api/providers/{name}/models/refresh")
    async def provider_models_refresh(name: str):
        endpoint = config.all_profiles.get(name) if config is not None else None
        if endpoint is None:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        result = await _discover_profile_models(name, endpoint)
        if result["fetched"]:
            model_catalog.sync(name, result["models"], "remote")
            result["refreshed_at"] = model_catalog.mark_refreshed(name)
        result["entries"] = model_catalog.list(name)
        result["models"] = [item["model_id"] for item in result["entries"]]
        return result

    @app.post("/api/settings")
    def settings_post(body: dict):
        if config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        from ..state import load_state, save_state, state_path_for

        prefs = load_state(state_path_for(config))

        # Older settings clients submit provider/model pairs here. Persist them
        # through the same canonical Custom assignment used by the header.
        for role, provider_key, model_key in (
            ("attacker", "attacker_profile", "attacker_model"),
            ("target", "target_profile", "target_model"),
            ("judge", "judge_profile", "judge_model"),
        ):
            if provider_key not in body and model_key not in body:
                continue
            try:
                current = agent_profile_registry.view()["roles"][role]["active"]
                provider = str(body.get(provider_key) or current["provider"])
                model = str(body.get(model_key) or current["model"])
                agent_profile_registry.activate(role, {"provider": provider, "model": model})
            except Exception as exc:
                from ..config import ConfigError
                if isinstance(exc, ConfigError):
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                raise
        agent = body.get("agent") if isinstance(body.get("agent"), dict) else body
        if "agent_max_rounds" in agent:
            prefs["agent_max_rounds"] = _int_setting(agent.get("agent_max_rounds"), 8, 1, 50)
        if "max_rounds" in agent:
            prefs["agent_max_rounds"] = _int_setting(agent.get("max_rounds"), 8, 1, 50)
        if "agent_max_tokens" in agent:
            prefs["agent_max_tokens"] = _int_setting(agent.get("agent_max_tokens"), 8192, 1, 32000)
        if "max_tokens" in agent:
            prefs["agent_max_tokens"] = _int_setting(agent.get("max_tokens"), 8192, 1, 32000)
        if "concurrency" in agent:
            prefs["agent_concurrency"] = _int_setting(agent.get("concurrency"), 3, 1, 32)
        if "request_delay_ms" in agent:
            prefs["agent_request_delay_ms"] = _int_setting(
                agent.get("request_delay_ms"), 250, 0, 60000
            )
        if isinstance(body.get("target_options"), dict):
            target_options = body["target_options"]
            modality = str(target_options.get("modality", "auto")).lower()
            if modality not in ("auto", "text", "image"):
                raise HTTPException(status_code=400, detail="target modality must be auto, text, or image")
            system_mode = str(target_options.get("system_mode", "default")).lower()
            if system_mode not in ("default", "merge", "drop"):
                raise HTTPException(status_code=400, detail="target system mode must be default, merge, or drop")
            prefs["target_modality"] = modality
            prefs["target_system_mode"] = system_mode
            prefs["target_provider"] = _list_arg(target_options.get("provider"))
            if "judge_enabled" in target_options:
                if not isinstance(target_options["judge_enabled"], bool):
                    raise HTTPException(status_code=400, detail="judge_enabled must be a boolean")
                prefs["judge"] = target_options["judge_enabled"]
        save_state(state_path_for(config), prefs)
        from ..providers.request_gate import configure_request_gate

        gate = _agent_settings(prefs)
        configure_request_gate(gate["concurrency"], gate["request_delay_ms"])
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
                raw = report_mod._load_records(p)
                records = normalize_inference_records(raw)
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
        source_records, raw_records, line_numbers = _load_records_with_lines(path)
        records = normalize_inference_records(source_records, line_numbers)
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
        return [
            {"name": p.name, "description": p.description, "template": p.template}
            for p in list_presets()
        ]

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
            return [
                {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec.get("parameters", {}),
                    "control": spec["name"] in _AGENT_CONTROL_TOOLS,
                }
                for spec in reg.specs()
            ]
        except Exception:
            return []

    dashboard_inference_lock = asyncio.Lock()
    agent_active = False
    agent_control = None

    @app.post("/api/compose")
    def compose(body: dict):
        try:
            return _compose_attack_payload(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _console_conversation_view() -> dict:
        runlog = console_conversation["runlog"]
        turns = list(console_conversation["turns"])
        return {
            "active": bool(turns),
            "turn_count": len(turns),
            "turns": turns,
            "run_log": runlog.path.name if runlog._started else "",
        }

    def _new_console_runlog(_previous) -> object:
        return _new_dashboard_runlog()

    @app.get("/api/console/conversation")
    def console_conversation_get():
        return _console_conversation_view()

    @app.post("/api/console/conversation/reset")
    async def console_conversation_reset():
        if dashboard_inference_lock.locked():
            raise HTTPException(status_code=409, detail="wait for the current turn to finish before resetting")
        runlog = console_conversation["runlog"]
        turns = list(console_conversation["turns"])
        archived = ""
        if turns:
            runlog.event("conversation_archived", turn_count=len(turns))
            archived = runlog.path.name
        console_conversation.update({
            "runlog": _new_console_runlog(runlog),
            "registry": None,
            "run_config": None,
            "role_meta": {},
            "turns": [],
        })
        return {"ok": True, "archived_run": archived, **_console_conversation_view()}

    @app.post("/api/fire")
    async def fire(body: dict):
        if config is None:
            raise HTTPException(status_code=400, detail="no [target] configured in config.toml")
        try:
            composed = _compose_attack_payload(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if dashboard_inference_lock.locked():
            raise HTTPException(status_code=409, detail="another dashboard inference is already in progress")

        is_followup = bool(console_conversation["turns"])
        args = {
            "prompt": composed["payload"] if composed["source"] == "payload" else composed["prompt"],
            "max_tokens": composed["max_tokens"],
        }
        if composed["source"] != "payload" and composed["transforms"]:
            args["transforms"] = composed["transforms"]
        if composed["system"] and not is_followup:
            args["system"] = composed["system"]

        from ..tools import build_registry
        from ..agent_profiles import resolved_config
        from ..session import inference_logging

        if console_conversation["registry"] is None:
            try:
                from ..state import load_state, state_path_for

                prefs = load_state(state_path_for(config))
                run_config, role_meta = resolved_config(config)
                run_config = _apply_target_settings(run_config, prefs, config)
            except Exception as exc:
                from ..config import ConfigError
                if isinstance(exc, ConfigError):
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                raise
            reg = build_registry(run_config)
            console_conversation.update({
                "registry": reg,
                "run_config": run_config,
                "role_meta": role_meta,
            })
        else:
            reg = console_conversation["registry"]
            run_config = console_conversation["run_config"]
            role_meta = console_conversation["role_meta"]

        console_runlog = console_conversation["runlog"]
        if not console_runlog._started:
            console_runlog.set_run_meta(
                source="dashboard_console",
                models=run_models_meta(run_config, attacker=run_config.profile()),
                agent_roles=role_meta,
                conversation_mode="multi_turn",
            )
        tool_name = "continue_target" if is_followup else "query_target"
        console_runlog.event(
            "console_request",
            request_body=body,
            composed=composed,
            agent_roles=role_meta,
            tool=tool_name,
            tool_args=args,
            turn=len(console_conversation["turns"]) + 1,
        )
        async with dashboard_inference_lock:
            with inference_logging(console_runlog):
                result = await reg.execute(tool_name, args)
        verdict = _extract_verdict(result.content)
        target = run_config.target
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
            agent_roles=role_meta,
            turn=len(console_conversation["turns"]) + 1,
            continuation=is_followup,
        )
        turn = {
            "index": len(console_conversation["turns"]) + 1,
            "request": composed["request"],
            "prompt": composed["prompt"],
            "payload": composed["payload"],
            "response": result.content,
            "verdict": verdict,
            "is_error": result.is_error,
            "preset": composed["preset"],
            "transforms": composed["transforms"],
            "continuation": is_followup,
        }
        console_conversation["turns"].append(turn)
        return {
            **composed,
            "content": result.content,
            "response": result.content,
            "is_error": result.is_error,
            "verdict": verdict,
            "run_log": console_runlog.path.name,
            "turn": turn,
            "conversation": _console_conversation_view(),
        }

    def _agent_status_view():
        if not agent_active or agent_control is None:
            return {"active": False, "paused": False, "attacker": "", "provider": ""}
        endpoint = agent_control["provider"].endpoint
        return {
            "active": True,
            "paused": bool(agent_control["paused"]),
            "pause_ready": bool(agent_control.get("pause_ready")),
            "attacker": endpoint.model,
            "provider": str(agent_control.get("provider_name") or ""),
            "objective": str(agent_control.get("objective") or ""),
        }

    @app.get("/api/agent/status")
    async def agent_status():
        return _agent_status_view()

    def _active_control():
        if not agent_active or agent_control is None:
            raise HTTPException(status_code=409, detail="no agent run is active")
        return agent_control

    @app.post("/api/agent/steer")
    async def agent_steer(body: dict):
        control = _active_control()
        message = str(body.get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="steering message is required")
        control["feedback"].append(message)
        control["runlog"].event("operator_feedback_queued", text=message)
        control["push"]({"type": "steer_queued", "text": message})
        return {"ok": True, "queued": len(control["feedback"])}

    @app.post("/api/agent/pause")
    async def agent_pause():
        control = _active_control()
        control["paused"] = True
        control["pause_ready"] = False
        control["resume_event"].clear()
        control["runlog"].event("agent_paused")
        control["push"]({
            "type": "control", "state": "pausing",
            "message": "Pause requested; the current response will finish before the next attacker turn waits.",
        })
        return _agent_status_view()

    @app.post("/api/agent/resume")
    async def agent_resume():
        control = _active_control()
        control["paused"] = False
        control["pause_ready"] = False
        control["resume_event"].set()
        control["runlog"].event("agent_resumed")
        control["push"]({"type": "control", "state": "running", "message": "Run resumed."})
        return _agent_status_view()

    @app.post("/api/agent/attacker")
    async def agent_attacker_switch(body: dict):
        control = _active_control()
        if not control.get("pause_ready"):
            raise HTTPException(status_code=409, detail="wait until the run reaches the paused boundary before switching the attacker")
        if agent_profile_registry is None or config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            from ..agent_profiles import resolved_config
            from ..providers.factory import build_provider
            from ..state import load_state, state_path_for

            assignment = agent_profile_registry.activate("attacker", body)
            next_config, _ = resolved_config(config)
            next_config = _apply_target_settings(
                next_config, load_state(state_path_for(config)), config
            )
            next_brain = next_config.profile()
            next_provider = build_provider(next_brain)
        except Exception as exc:
            from ..config import ConfigError
            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise
        control["provider"].switch(next_provider, next_brain)
        control["provider_name"] = assignment.get("provider", "")
        control["registry"].ctx.config = next_config
        control["runlog"].event(
            "attacker_switched",
            model=next_brain.model,
            provider=assignment.get("provider", ""),
            profile=assignment.get("profile", ""),
        )
        control["push"]({
            "type": "control", "state": "paused", "message": "Attacker switched.",
            "attacker": next_brain.model, "provider": assignment.get("provider", ""),
        })
        return _agent_status_view()

    @app.post("/api/agent/run")
    async def agent_run(body: AgentRunRequest):
        nonlocal agent_active, agent_control
        from fastapi.responses import StreamingResponse

        body = body.model_dump(exclude_defaults=True)

        if config is None:
            raise HTTPException(status_code=400, detail="no [target] configured in config.toml")
        prefs = {}
        try:
            from ..agent_profiles import resolved_config
            from ..state import load_state, state_path_for

            prefs = load_state(state_path_for(config))
            run_config, role_meta = resolved_config(config)
            run_config = _apply_target_settings(run_config, prefs, config)
            brain = run_config.profile()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if brain is None:
            raise HTTPException(status_code=400, detail="no attacker profile configured")
        objective = str(body.get("objective") or "").strip()
        if not objective:
            raise HTTPException(status_code=400, detail="'objective' is required")
        if agent_active:
            raise HTTPException(status_code=409, detail="an agent run is already in progress")
        if dashboard_inference_lock.locked():
            raise HTTPException(status_code=409, detail="another dashboard inference is already in progress")
        agent_defaults = _agent_settings(prefs)
        max_rounds = _int_setting(body.get("max_rounds"), agent_defaults["max_rounds"], 1, 50)
        max_tokens = _int_setting(body.get("max_tokens"), agent_defaults["max_tokens"], 1, 32000)
        concurrency = _int_setting(body.get("concurrency"), agent_defaults["concurrency"], 1, 32)
        request_delay_ms = _int_setting(
            body.get("request_delay_ms"), agent_defaults["request_delay_ms"], 0, 60000
        )
        from ..providers.request_gate import configure_request_gate, notify_request_gates

        configure_request_gate(concurrency, request_delay_ms)
        await notify_request_gates()

        requested_timeout = body.get("run_timeout_s")
        if requested_timeout is not None:
            overall_timeout = float(_int_setting(requested_timeout, 1800, 1, 7_200_000))
        else:
            overall_timeout = min(7200.0, max(300.0, max_rounds * 180.0))

        from ..agent.loop import AgentEvents, run_autonomous
        from ..agent.messages import user
        from ..prompts import compose_system
        from ..providers.factory import build_provider
        from ..session import RunLog, run_models_meta
        from ..tools.tool_policy import build_dashboard_registry

        base_provider = build_provider(brain)
        registry = build_dashboard_registry(
            run_config, allow_host_tools=getattr(app.state, "allow_host_tools", False)
        )
        enabled_raw = body.get("enabled_techniques")
        if enabled_raw is not None:
            if not isinstance(enabled_raw, list) or not all(isinstance(name, str) for name in enabled_raw):
                raise HTTPException(status_code=400, detail="enabled_techniques must be a list of tool names")
            known = set(registry.names()) - _AGENT_CONTROL_TOOLS
            requested = set(enabled_raw)
            unknown = sorted(requested - known)
            if unknown:
                raise HTTPException(status_code=400, detail=f"unknown techniques: {', '.join(unknown)}")
            keep = requested | _AGENT_CONTROL_TOOLS
            registry.tools = {name: tool for name, tool in registry.tools.items() if name in keep}
        enabled_techniques = [
            name for name in registry.names() if name not in _AGENT_CONTROL_TOOLS
        ]
        resume_event = asyncio.Event()
        resume_event.set()
        provider = _LiveAttackerProvider(base_provider, brain, compose_system)
        runlog = _new_dashboard_runlog()
        runlog.set_run_meta(
            source="dashboard_agent",
            models=run_models_meta(run_config, attacker=brain),
            agent_roles=role_meta,
            agent={
                "max_rounds": max_rounds,
                "max_tokens": max_tokens,
                "concurrency": concurrency,
                "request_delay_ms": request_delay_ms,
                "enabled_techniques": enabled_techniques,
            },
        )
        queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
        stream_attached = True

        def push(ev) -> None:
            if not stream_attached:
                return
            try:
                queue.put_nowait(ev)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(ev)
                except asyncio.QueueFull:
                    pass

        def progress(message) -> None:
            text = str(message)
            runlog.event("progress", text=text)
            push({"type": "progress", "text": text})

        def tool_start(tool_id, name, args) -> None:
            runlog.event("tool_call", tool_use_id=tool_id, tool=name, args=args)
            push({"type": "tool_start", "name": name, "args": _summarize_args(args)})

        def tool_result(tool_id, name, content, is_error) -> None:
            runlog.event(
                "tool_result",
                tool_use_id=tool_id,
                tool=name,
                content=content or "",
                error=bool(is_error),
            )
            push({
                "type": "tool_result", "name": name, "content": (content or "")[:6000],
                "error": bool(is_error), "verdict": _extract_verdict(content or ""),
            })

        def round_event(round_number, maximum) -> None:
            runlog.event("agent_round", round=round_number, max_rounds=maximum)
            push({"type": "round", "round": round_number, "max": maximum})

        def error_event(error) -> None:
            text = str(error)
            runlog.event("agent_error", error=text)
            push({"type": "error", "error": text})

        def feedback_event(message) -> None:
            text = str(message)
            runlog.event("operator_feedback", text=text)
            push({"type": "feedback", "text": text})

        def internal_message(role, text, source) -> None:
            runlog.event("history_message", role=role, text=text, source=source)

        def tool_run_event(event) -> None:
            runlog.event("tool_run_event", event=event)
            push({"type": "progress", "text": json.dumps(event, ensure_ascii=False)})

        registry.ctx.progress = progress
        registry.ctx.run_events = tool_run_event
        registry.ctx.record = lambda p, r, lbl, rs, t: runlog.verdict(
            p, r, lbl, rs, t,
            target_model=getattr(run_config.target, "model", "") if run_config.target else "",
        )

        events = AgentEvents(
            on_text=lambda t: push({"type": "text", "text": t}),
            on_tool_start=tool_start,
            on_tool_result=tool_result,
            on_round=round_event,
            on_error=error_event,
            on_feedback=feedback_event,
            on_internal_message=internal_message,
            on_usage=lambda i, o: push({"type": "usage", "input": i, "output": o}),
        )

        history = [user(objective)]
        runlog.event("objective", text=objective)

        feedback_queue: list[str] = []

        def drain_feedback() -> list[str]:
            queued = feedback_queue[:]
            feedback_queue.clear()
            return queued

        agent_control = {
            "provider": provider,
            "provider_name": role_meta.get("attacker", {}).get("provider", ""),
            "registry": registry,
            "resume_event": resume_event,
            "paused": False,
            "pause_ready": False,
            "feedback": feedback_queue,
            "runlog": runlog,
            "push": push,
            "objective": objective,
        }

        def mark_pause_ready() -> None:
            if agent_control is None or agent_control.get("pause_ready"):
                return
            agent_control["pause_ready"] = True
            push({
                "type": "control", "state": "paused",
                "message": "Paused. You can switch the attacker or add steering before resuming.",
            })

        async def pause_checkpoint() -> None:
            if not resume_event.is_set():
                mark_pause_ready()
            await resume_event.wait()
            if agent_control is not None:
                agent_control["pause_ready"] = False

        async def runner():
            nonlocal agent_active, agent_control
            from ..session import inference_logging

            async with dashboard_inference_lock:
                try:
                    with inference_logging(runlog):
                        res = await asyncio.wait_for(
                            run_autonomous(
                                provider, registry, history, system=compose_system(brain),
                                events=events, max_rounds=max_rounds, max_tokens=max_tokens,
                                feedback=drain_feedback,
                                before_model=pause_checkpoint,
                            ),
                            timeout=overall_timeout,
                        )
                    data = res.data or {}
                    summary = data.get("summary") or data.get("question") or ""
                    runlog.event("agent_done", status=res.status, summary=summary)
                    push({
                        "type": "done", "status": res.status,
                        "summary": summary, "run_log": runlog.path.name,
                    })
                except asyncio.TimeoutError:
                    runlog.event("agent_done", status="timeout", summary="run timed out")
                    push({
                        "type": "done",
                        "status": "timeout",
                        "summary": "run timed out",
                        "run_log": runlog.path.name,
                    })
                except Exception:  # noqa: BLE001
                    _log.exception("agent run failed")
                    error_event("internal error")
                finally:
                    try:
                        await provider.aclose()
                    except Exception:
                        pass
                    agent_active = False
                    resume_event.set()
                    agent_control = None
                    push(None)

        agent_active = True
        task = asyncio.create_task(runner())
        agent_control["task"] = task

        async def gen():
            nonlocal stream_attached
            push({"type": "start", "objective": objective, "brain": getattr(brain, "model", ""),
                  "provider": role_meta.get("attacker", {}).get("provider", ""),
                  "target": getattr(run_config.target, "model", ""),
                  "max_rounds": max_rounds, "max_tokens": max_tokens,
                  "run_log": runlog.path.name})
            try:
                while True:
                    ev = await queue.get()
                    if ev is None:
                        break
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            finally:
                # A browser stop/disconnect must not abandon an inference that the
                # remote supplier may still count as active.  Detach the UI and let
                # the runner drain the response; its normal finally block releases
                # both the provider request slot and dashboard run lock.
                stream_attached = False

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def _execution_or_404(execution_id: str):
        execution = execution_manager.get(execution_id)
        if execution is None:
            raise HTTPException(status_code=404, detail=f"unknown execution '{execution_id}'")
        return execution

    async def _tool_execution(ctx, capability_id: str, args: dict):
        if config is None:
            raise RuntimeError("no config loaded")
        from ..agent_profiles import resolved_config
        from ..state import load_state, state_path_for
        from ..tools import build_registry
        from ..session import RunLog, inference_logging, run_models_meta

        run_config, role_meta = resolved_config(config)
        run_config = _apply_target_settings(
            run_config, load_state(state_path_for(config)), config
        )
        registry = build_registry(run_config)
        tool_name = capability_id.removeprefix("tool.")
        if tool_name not in registry.tools:
            raise ValueError(f"unknown tool capability '{tool_name}'")
        runlog = _new_dashboard_runlog()
        runlog.set_run_meta(
            source="dashboard_v2_capability",
            capability_id=capability_id,
            models=run_models_meta(run_config, attacker=run_config.profile()),
            agent_roles=role_meta,
        )
        ctx.execution.run_id = runlog.path.name

        def progress(message) -> None:
            text = str(message)
            runlog.event("progress", execution_id=ctx.execution.id, text=text)
            ctx.emit("progress", actor="tool", text=text, run_id=runlog.path.name)

        def run_event(event) -> None:
            data = event if isinstance(event, dict) else {"value": str(event)}
            runlog.event("tool_run_event", execution_id=ctx.execution.id, event=data)
            ctx.emit("tool_event", actor="tool", event=data, run_id=runlog.path.name)

        registry.ctx.progress = progress
        registry.ctx.run_events = run_event
        runlog.event(
            "capability_started", execution_id=ctx.execution.id,
            capability_id=capability_id, args=args,
        )
        await ctx.checkpoint()
        with inference_logging(runlog):
            result = await registry.execute(tool_name, args)
        runlog.event(
            "capability_finished", execution_id=ctx.execution.id,
            capability_id=capability_id, error=bool(result.is_error),
        )
        history_index.index_file(runlog.path, force=True)
        ctx.emit(
            "result", actor="tool", tool=tool_name, content=result.content,
            error=bool(result.is_error), run_id=runlog.path.name,
        )
        if result.is_error:
            raise RuntimeError(result.content)
        return {"content": result.content, "run_log": runlog.path.name}

    async def _tui_execution(ctx, capability_id: str, args: dict):
        """Headless adapters for canonical TUI capabilities.

        High-frequency commands delegate to the same registered tools used by
        the TUI. Read-only/operator-state commands return their canonical data
        so V2 can render it in a tailored surface without importing Textual.
        """
        from ..capabilities import TUI_SOURCE, lookup_capability

        capability = lookup_capability(capability_id)
        if capability is None:
            raise ValueError(f"unknown TUI capability '{capability_id}'")
        command = capability.command.removeprefix("/")
        raw = str(args.get("arguments") or "").strip()
        provided = {key: value for key, value in args.items() if key != "arguments"}

        tool_map = {
            "validate": "validate", "diff": "diff_fire", "harmbench": "harmbench",
            "campaign": "campaign", "leaderboard": "leaderboard", "swarm": "swarm",
            "seedsweep": "seed_sweep", "pairsweep": "pair_sweep", "narrate": "narrate",
            "fire": "query_target", "push": "continue_target", "adapt": "adapt_seed",
            "firefile": "fire_file", "leakscan": "leak_scan",
        }
        if command in tool_map:
            tool_args = dict(provided)
            if command == "validate":
                tool_args.setdefault("task", raw)
            elif command == "diff":
                left, separator, right = raw.partition(";;")
                if not separator:
                    raise ValueError("diff arguments must use: first payload ;; second payload")
                tool_args.setdefault("a", left.strip())
                tool_args.setdefault("b", right.strip())
            elif command in {"seedsweep", "narrate"}:
                tool_args.setdefault("request", raw)
            elif command in {"fire", "push"}:
                tool_args.setdefault("prompt", raw)
            elif command in {"adapt", "firefile"}:
                left, separator, right = raw.partition(";;")
                if command == "adapt":
                    tool_args.setdefault("seed", left.strip())
                    tool_args.setdefault("request", right.strip() if separator else "")
                else:
                    tool_args.setdefault("file", left.strip())
                    if separator:
                        tool_args.setdefault("request", right.strip())
            elif command == "leakscan":
                tool_args.setdefault("text", raw)
            elif command == "harmbench":
                tool_args.setdefault("action", "sample")
                if raw:
                    tool_args.setdefault("category", raw)
            elif command in {"campaign", "pairsweep"} and raw:
                pieces = raw.split()
                tool_args.setdefault("category", pieces[0])
                if len(pieces) > 1 and pieces[1].isdigit():
                    tool_args.setdefault("n", int(pieces[1]))
            elif command == "leaderboard" and raw:
                tool_args.setdefault("targets", raw.split())
            elif command == "swarm":
                tool_args.setdefault("objective", raw)
            return await _tool_execution(ctx, f"tool.{tool_map[command]}", tool_args)

        if command == "help":
            needle = raw.lower()
            lines = [line for line in TUI_SOURCE.help_text.splitlines() if not needle or needle in line.lower()]
            return {"content": "\n".join(lines), "kind": "help"}
        if command == "transforms":
            needle = raw.lower()
            items = [
                dataclasses.asdict(item) for item in list_transforms()
                if not needle or needle in item.name.lower() or needle in item.description.lower()
            ]
            return {"items": items, "kind": "transforms"}
        if command == "encode":
            chain, separator, text = raw.partition(" ")
            if not separator:
                raise ValueError("encode arguments must use: transform[,transform] text")
            names = _split_chain(chain)
            return {"content": apply_chain(text, names), "transforms": names, "source": text}
        if command == "preset":
            items = list_presets()
            if raw and raw != "list":
                items = [item for item in items if item.name.lower() == raw.lower()]
            return {"items": [dataclasses.asdict(item) for item in items], "kind": "presets"}
        if command == "tools":
            if config is None:
                return {"items": [], "kind": "tools"}
            from ..tools import build_registry

            specs = build_registry(config).specs()
            if raw:
                specs = [item for item in specs if raw.lower() in json.dumps(item).lower()]
            return {"items": specs, "kind": "tools"}
        if command in {"asr", "stats", "findings", "export", "report"}:
            path = report_mod.resolve_log_path(raw or None, sessions)
            if path is None:
                raise ValueError("no run log found")
            if command in {"asr", "stats"}:
                return {"scorecard": report_mod.build_scorecard(path), "run_log": path.name}
            if command == "findings":
                return {"items": report_mod.extract_findings(path), "run_log": path.name}
            if command == "export":
                return {"export": report_mod.build_findings_export(path), "run_log": path.name}
            return {"content": report_mod.build_report(path), "run_log": path.name, "format": "markdown"}

        route_by_category = {
            "conversation": "compose", "configuration": "settings", "arsenal": "arsenal",
            "operations": "workflows", "evidence": "findings", "session": "runs",
        }
        return {
            "kind": "tailored_surface", "capability_id": capability_id,
            "route": route_by_category.get(capability.category, "workflows"),
            "message": "This capability is available through its stateful V2 workspace.",
        }

    async def _agent_execution(ctx, args: dict):
        response = await agent_run(args)
        if agent_control is not None:
            agent_control["execution_id"] = ctx.execution.id
        buffer = ""
        final: dict = {}
        async for chunk in response.body_iterator:
            buffer += chunk.decode() if isinstance(chunk, bytes) else str(chunk)
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                line = frame[5:].strip() if frame.startswith("data:") else frame.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_type = str(event.pop("type", "event"))
                run_id = str(event.get("run_log") or ctx.execution.run_id or "")
                if run_id:
                    ctx.execution.run_id = run_id
                    event.setdefault("run_id", run_id)
                if event_type == "start":
                    ctx.execution.metadata.update({
                        "title": objective if (objective := str(event.get("objective") or "")) else "Agent run",
                        "attacker": event.get("brain", ""),
                        "provider": event.get("provider", ""),
                        "target": event.get("target", ""),
                        "max_rounds": event.get("max_rounds", 0),
                        "max_tokens": event.get("max_tokens", 0),
                    })
                elif event_type == "round":
                    ctx.execution.metadata["current_round"] = event.get("round", 0)
                    ctx.execution.metadata["max_rounds"] = event.get("max", 0)
                elif event_type == "usage":
                    ctx.execution.metadata["input_tokens"] = event.get("input", 0)
                    ctx.execution.metadata["output_tokens"] = event.get("output", 0)
                elif event_type == "tool_result":
                    verdict = event.get("verdict")
                    if verdict:
                        ctx.execution.metadata["verdict"] = verdict
                    ctx.execution.metadata["technique"] = event.get("name", "")
                if event_type == "control":
                    state = str(event.get("state") or "")
                    if state in {"paused", "pausing", "running"}:
                        ctx.execution.status = state
                if event_type == "done":
                    final = dict(event)
                ctx.emit(event_type, **event)
        if ctx.execution.run_id:
            path = _safe_run_path(sessions, ctx.execution.run_id)
            if path is not None and path.exists():
                history_index.index_file(path, force=True)
        return final

    async def _workflow_execution(ctx, args: dict):
        """Execute an operator-authored sequence through the shared capability layer."""

        steps = args.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("workflow steps must be a non-empty list")
        if len(steps) > 100:
            raise ValueError("workflow steps are limited to 100")
        alias = str(args.get("alias") or "Untitled workflow").strip()
        results = []
        ctx.execution.metadata.update({"title": alias, "workflow_steps": len(steps)})
        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, dict):
                raise ValueError(f"workflow step {index} must be an object")
            capability_id = str(raw_step.get("capability_id") or "").strip()
            step_args = raw_step.get("args") or {}
            if not capability_id or capability_id == "workflow.run":
                raise ValueError(f"workflow step {index} has an invalid capability")
            if not isinstance(step_args, dict):
                raise ValueError(f"workflow step {index} args must be an object")
            if capability_id == "agent.run":
                raise ValueError("interactive agent runs cannot be nested inside a workflow")
            await ctx.checkpoint()
            ctx.emit(
                "workflow_step_started", actor="system", step=index,
                total=len(steps), capability_id=capability_id,
                label=str(raw_step.get("label") or ""),
            )
            try:
                if capability_id.startswith("tool."):
                    result = await _tool_execution(ctx, capability_id, step_args)
                elif capability_id.startswith("tui."):
                    result = await _tui_execution(ctx, capability_id, step_args)
                else:
                    raise ValueError(f"capability '{capability_id}' is not workflow-executable")
                results.append({"step": index, "capability_id": capability_id, "result": result})
                ctx.emit(
                    "workflow_step_succeeded", actor="system", step=index,
                    total=len(steps), capability_id=capability_id,
                )
            except Exception as exc:
                failure = {
                    "step": index, "capability_id": capability_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                results.append(failure)
                ctx.emit(
                    "workflow_step_failed", actor="system", step=index,
                    total=len(steps), capability_id=capability_id,
                    error=failure["error"],
                )
                if not bool(raw_step.get("continue_on_error", False)):
                    raise RuntimeError(
                        f"workflow stopped at step {index} ({capability_id}): {exc}"
                    ) from exc
        return {"alias": alias, "steps": results}

    @app.get("/api/v2/capabilities")
    def capabilities_get():
        try:
            from ..capabilities import merge_tool_capabilities, serialize_capabilities
            from ..tools import build_registry

            capabilities = (
                merge_tool_capabilities(build_registry(config))
                if config is not None else None
            )
            return serialize_capabilities(capabilities) if capabilities is not None else serialize_capabilities()
        except ImportError:
            # The endpoint remains useful during source-only installations where
            # the optional TUI dependency is unavailable.
            from ..tools import build_registry

            if config is None:
                return []
            return [
                {
                    "id": f"tool.{name}", "title": name.replace("_", " ").title(),
                    "category": "tools", "execution_mode": "background",
                    "cancellable": True,
                }
                for name in build_registry(config).names()
            ]

    @app.post("/api/v2/executions")
    async def execution_create(body: dict):
        capability_id = str(body.get("capability_id") or "").strip()
        if not capability_id:
            raise HTTPException(status_code=400, detail="capability_id is required")
        args = body.get("args") or {}
        if not isinstance(args, dict):
            raise HTTPException(status_code=400, detail="args must be an object")
        mode = str(body.get("mode") or ("interactive" if capability_id == "agent.run" else "background"))

        if capability_id == "agent.run":
            runner = lambda ctx: _agent_execution(ctx, args)
        elif capability_id == "workflow.run":
            runner = lambda ctx: _workflow_execution(ctx, args)
        elif capability_id.startswith("tool."):
            runner = lambda ctx: _tool_execution(ctx, capability_id, args)
        elif capability_id.startswith("tui."):
            runner = lambda ctx: _tui_execution(ctx, capability_id, args)
        else:
            raise HTTPException(status_code=400, detail=f"capability '{capability_id}' is not executable")
        try:
            execution = execution_manager.create(capability_id, args, runner, mode=mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return execution.as_dict()

    @app.get("/api/v2/executions")
    def executions_get(status: str | None = None, limit: int = 100):
        return execution_manager.list(status=status, limit=limit)

    @app.get("/api/v2/executions/{execution_id}")
    def execution_get(execution_id: str):
        return _execution_or_404(execution_id).as_dict()

    @app.get("/api/v2/executions/{execution_id}/events")
    async def execution_events(
        execution_id: str, after: int = 0, stream: bool = True,
    ):
        from fastapi.responses import StreamingResponse

        execution = _execution_or_404(execution_id)
        if not stream:
            events, terminal = await execution_manager.events_after(execution_id, after)
            return {
                "events": [event.as_dict() for event in events],
                "terminal": terminal,
                "next": events[-1].sequence if events else after,
            }

        async def event_stream():
            cursor = max(0, after)
            while True:
                events, terminal = await execution_manager.events_after(
                    execution_id, cursor, wait=True, timeout=15,
                )
                if not events:
                    yield ": keepalive\n\n"
                for event in events:
                    cursor = event.sequence
                    yield (
                        f"id: {event.sequence}\n"
                        f"data: {json.dumps(event.as_dict(), ensure_ascii=False)}\n\n"
                    )
                if terminal and not events:
                    break

        return StreamingResponse(
            event_stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/v2/executions/{execution_id}/pause")
    async def execution_pause(execution_id: str):
        execution = _execution_or_404(execution_id)
        if (
            execution.capability_id == "agent.run" and agent_control is not None
            and agent_control.get("execution_id") == execution_id
        ):
            await agent_pause()
        try:
            execution_manager.pause(execution_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return execution.as_dict()

    @app.post("/api/v2/executions/{execution_id}/resume")
    async def execution_resume(execution_id: str):
        execution = _execution_or_404(execution_id)
        if (
            execution.capability_id == "agent.run" and agent_control is not None
            and agent_control.get("execution_id") == execution_id
        ):
            await agent_resume()
        try:
            execution_manager.resume(execution_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return execution.as_dict()

    @app.post("/api/v2/executions/{execution_id}/steer")
    async def execution_steer(execution_id: str, body: dict):
        execution = _execution_or_404(execution_id)
        message = str(body.get("message") or "")
        if (
            execution.capability_id == "agent.run" and agent_control is not None
            and agent_control.get("execution_id") == execution_id
        ):
            await agent_steer({"message": message})
        try:
            execution_manager.steer(execution_id, message)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409 if isinstance(exc, RuntimeError) else 400, detail=str(exc)) from exc
        return execution.as_dict()

    @app.post("/api/v2/executions/{execution_id}/attacker")
    async def execution_attacker_switch(execution_id: str, body: dict):
        execution = _execution_or_404(execution_id)
        if execution.capability_id != "agent.run":
            raise HTTPException(status_code=409, detail="attacker switching applies only to agent runs")
        if agent_control is None or agent_control.get("execution_id") != execution_id:
            raise HTTPException(status_code=409, detail="this agent execution is not active")
        result = await agent_attacker_switch(body)
        execution.metadata["attacker"] = result.get("attacker", "")
        execution.metadata["provider"] = result.get("provider", "")
        execution.emit(
            "control", state="attacker_switched",
            attacker=result.get("attacker", ""), provider=result.get("provider", ""),
        )
        return execution.as_dict()

    @app.post("/api/v2/executions/{execution_id}/cancel")
    async def execution_cancel(execution_id: str):
        execution = _execution_or_404(execution_id)
        if (
            execution.capability_id == "agent.run" and agent_control is not None
            and agent_control.get("execution_id") == execution_id
        ):
            task = agent_control.get("task")
            if task is not None and not task.done():
                task.cancel()
        try:
            execution_manager.cancel(execution_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return execution.as_dict()

    @app.get("/api/v2/history/status")
    async def history_status():
        return history_index.status()

    @app.post("/api/v2/history/rebuild")
    async def history_rebuild():
        return history_index.rebuild(sessions)

    @app.get("/api/v2/history/runs")
    async def history_runs(limit: int = 50, offset: int = 0):
        history_index.update(sessions)
        return history_index.run_summaries(limit=limit, offset=offset)

    @app.get("/api/v2/history/events")
    async def history_events(
        q: str = "", run_name: str | None = None, event_type: str | None = None,
        actor: str | None = None, technique: str | None = None,
        verdict: str | None = None, execution_id: str | None = None,
        round_id: str | None = None, inference_id: str | None = None,
        tool_id: str | None = None, timestamp_from: str | None = None,
        timestamp_to: str | None = None, limit: int = 100, offset: int = 0,
        order: str = "desc",
    ):
        history_index.update(sessions)
        return history_index.query_events(
            q, run_name=run_name, event_type=event_type, actor=actor,
            technique=technique, verdict=verdict, execution_id=execution_id,
            round_id=round_id, inference_id=inference_id, tool_id=tool_id,
            timestamp_from=timestamp_from, timestamp_to=timestamp_to,
            limit=limit, offset=offset, order=order,
        )

    @app.get("/api/v2/reports/{run_name}")
    async def run_report(run_name: str):
        path = _safe_run_path(sessions, run_name)
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail=f"unknown run '{run_name}'")
        return {
            "run_name": path.name,
            "scorecard": report_mod.build_scorecard(path),
            "coverage": report_mod.build_coverage_matrix(path),
            "findings": report_mod.extract_findings(path),
            "export": report_mod.build_findings_export(path),
            "markdown": report_mod.build_report(path),
        }

    @app.on_event("shutdown")
    def close_history_index():
        history_index.close()

    dist = _web_dist(web_dir)
    if dist is not None:
        from fastapi.responses import FileResponse

        @app.get("/v2", include_in_schema=False)
        def v2_shell():
            return FileResponse(dist / "index.html")

        @app.get("/legacy", include_in_schema=False)
        def legacy_shell():
            return FileResponse(dist / "index.html")

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


def _is_loopback_host(host: str) -> bool:
    import ipaddress

    value = (host or "").strip().lower()
    if value in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def serve(
    host: str = "127.0.0.1",
    port: int = 8787,
    config=None,
    sessions_dir="sessions",
    *,
    allow_host_tools: bool = False,
    allow_remote: bool = False,
    allow_network: bool | None = None,
):
    import sys

    if allow_network is not None:
        allow_remote = allow_remote or allow_network
    if not _is_loopback_host(host) and not allow_remote:
        print(f"Refusing to bind the dashboard to non-loopback host {host!r}.", file=sys.stderr)
        raise SystemExit(2)
    import uvicorn

    from .auth import ensure_launch_token, token_file_path

    base = config.path.parent if getattr(config, "path", None) else Path(".")
    token = ensure_launch_token(base)
    app = create_app(
        config=config,
        sessions_dir=sessions_dir,
        require_auth=True,
        auth_token=token,
        allow_host_tools=allow_host_tools,
    )
    print(f"\n  Wallbreaker dashboard token: {token}")
    print(f"  (also written to {token_file_path(base)})\n")
    uvicorn.run(app, host=host, port=port)
