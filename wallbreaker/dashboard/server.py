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
                findings_count = len(report_mod.extract_findings(log))
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
        path = sessions / name
        if ".." in name or "/" in name or not path.is_file():
            raise HTTPException(status_code=404, detail="run not found")
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
        return {
            "name": name,
            "total": len(records),
            "records": records,
            "raw_records": raw_records,
            "line_numbers": line_numbers,
        }

    @app.get("/api/findings")
    def findings():
        log = _latest()
        if log is None:
            return []
        try:
            return report_mod.extract_findings(log)
        except Exception:
            return []

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
