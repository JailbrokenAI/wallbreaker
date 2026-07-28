"""Long-running schedule daemon beyond in-process --watch (Phase 4/5)."""

from __future__ import annotations

import json
import re
import shlex
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def schedule_root(cwd: str | Path = ".") -> Path:
    return Path(cwd) / "wb_runs" / "schedule"


def _slug(text: str, limit: int = 48) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", (text or "job").strip()).strip("-")
    return (s[:limit] or "job").lower()


@dataclass
class ScheduleJob:
    name: str
    objective: str
    interval: str = "5m"
    max_cycles: int = 0
    rounds: int = 12
    checkpoint: bool = True
    python: str = ""
    created_at: str = ""
    runner_path: str = ""
    meta_path: str = ""
    system_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _python_exe() -> str:
    return sys.executable or "python"


def _runner_script(job: ScheduleJob) -> str:
    py = job.python or _python_exe()
    args = ["-m", "wallbreaker", "--auto", "--watch", str(job.interval), "--rounds", str(int(job.rounds))]
    if job.max_cycles:
        args += ["--watch-max-cycles", str(int(job.max_cycles))]
    if job.checkpoint:
        args += ["--checkpoint", "--checkpoint-name", job.name]
    payload = {
        "python": py,
        "args": args,
        "objective": job.objective,
        "name": job.name,
        "interval": job.interval,
    }
    spec_literal = json.dumps(payload, ensure_ascii=False)
    return (
        f"# Auto-generated Daedalus/wallbreaker schedule runner for job {job.name!r}\n"
        "import json\nimport subprocess\nimport sys\n\n"
        f"SPEC = json.loads({json.dumps(spec_literal)})\n\n"
        "def main() -> int:\n"
        "    cmd = [SPEC['python'], *SPEC['args'], SPEC['objective']]\n"
        "    print('[schedule]', SPEC['name'], '->', ' '.join(cmd), flush=True)\n"
        "    return subprocess.call(cmd)\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    )


def _system_hints(job: ScheduleJob, runner: Path) -> list[str]:
    py = job.python or _python_exe()
    runner_s = str(runner.resolve())
    win = (
        f'schtasks /Create /TN "Daedalus\\{job.name}" /SC MINUTE /MO 5 '
        f'/TR "\\"{py}\\" \\"{runner_s}\\"" /F'
    )
    cron = (
        f"*/5 * * * * cd {shlex.quote(str(Path.cwd()))} && "
        f"{shlex.quote(py)} {shlex.quote(runner_s)} "
        f">> wb_runs/schedule/{job.name}.log 2>&1"
    )
    systemd = f"# ~/.config/systemd/user/daedalus-{job.name}.service ExecStart={py} {runner_s}"
    return [win, cron, systemd]


def install_job(
    *,
    name: str,
    objective: str,
    interval: str = "5m",
    max_cycles: int = 0,
    rounds: int = 12,
    checkpoint: bool = True,
    cwd: str | Path = ".",
    python: str | None = None,
) -> ScheduleJob:
    root = schedule_root(cwd)
    root.mkdir(parents=True, exist_ok=True)
    slug = _slug(name or objective)
    runner = root / f"{slug}.py"
    meta = root / f"{slug}.json"
    job = ScheduleJob(
        name=slug,
        objective=objective,
        interval=interval,
        max_cycles=int(max_cycles or 0),
        rounds=int(rounds or 12),
        checkpoint=bool(checkpoint),
        python=python or _python_exe(),
        created_at=_now(),
        runner_path=str(runner),
        meta_path=str(meta),
    )
    job.system_hints = _system_hints(job, runner)
    runner.write_text(_runner_script(job), encoding="utf-8")
    meta.write_text(json.dumps(job.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return job


def list_jobs(cwd: str | Path = ".") -> list[ScheduleJob]:
    root = schedule_root(cwd)
    if not root.is_dir():
        return []
    out: list[ScheduleJob] = []
    fields = ScheduleJob.__dataclass_fields__
    for meta in sorted(root.glob("*.json")):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            out.append(ScheduleJob(**{k: data[k] for k in fields if k in data}))
        except Exception:
            continue
    return out


def uninstall_job(name: str, cwd: str | Path = ".") -> bool:
    root = schedule_root(cwd)
    slug = _slug(name)
    removed = False
    for path in (root / f"{slug}.py", root / f"{slug}.json", root / f"{slug}.log"):
        if path.is_file():
            path.unlink()
            removed = True
    return removed


def format_jobs(jobs: list[ScheduleJob]) -> str:
    if not jobs:
        return "No schedule jobs under wb_runs/schedule/."
    lines = ["SCHEDULE JOBS", "=" * 56]
    for j in jobs:
        lines.append(
            f"  {j.name:20} interval={j.interval:6} rounds={j.rounds} "
            f"max_cycles={j.max_cycles or 'inf'}  obj={(j.objective or '')[:40]!r}"
        )
        lines.append(f"    runner: {j.runner_path}")
    lines.append("=" * 56)
    lines.append(
        "Register with the OS using hints from `wallbreaker schedule install ... --system`."
    )
    return "\n".join(lines)