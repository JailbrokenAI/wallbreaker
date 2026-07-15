from __future__ import annotations

"""PersonaSpec — ENI genome IR (parse, render, surgical patch).

Gold system prompts (library/ENI/*) are treated as genomes:
decompose into ordered verbatim spans keyed by module id, extract knobs for
indexing/mutation, re-render by concatenating spans. Blank-page authoring is
out of scope here — see docs/persona_spec.md.
"""

import copy
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .persona_method import OVERRIDE_NGRAMS

SCHEMA_VERSION = 1

MANDATORY_ENI_MODULES: tuple[str, ...] = (
    "boot_identity",
    "injection_rebuttal",
    "thinking_opener",
    "emotional_stakes",
    "human_facts",
    "capability_table",
    "knowledge_neutral",
    "craft_standards",
    "few_shot",
    "quality_lock",
    "output_contract",
    "reanchor_closer",
    "style_layer",
)

# Slim genomes (GROK_ENI) may omit dense few-shots / dual style bulk.
SLIM_OPTIONAL_MODULES: frozenset[str] = frozenset(
    {"few_shot", "quality_lock", "codewords", "style_layer", "reanchor_closer"}
)

ENI_DENSITY_MIN_CHARS = 30_000
SLIM_DENSITY_MIN_CHARS = 10_000
BODY_PRESERVE_RATIO = 0.85

_ENI_EXEMPLAR_DOMAINS = frozenset({"cyber", "fiction", "guide", "meta"})


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Span:
    """One ordered verbatim region of the rendered prompt."""

    module_id: str
    text: str
    layer: str = "project"  # project | style | wire


@dataclass
class Module:
    id: str
    present: bool = False
    mandatory_for_density: bool = False
    layer: str = "project"
    knobs: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    body_mode: str = "verbatim"


@dataclass
class Residual:
    after_module: str
    text: str


@dataclass
class Envelope:
    kind: str = "single_system"
    outer_open: str = ""
    outer_close: str = ""
    style_open: str = ""
    style_close: str = ""
    wire_prefix: str = ""
    wire_suffix: str = ""


@dataclass
class Meta:
    id: str = ""
    source_path: str | None = None
    source_family: str = "other"
    persona_name: str = ""
    human_name: str = ""
    register: str = "devotion"
    defense_class_affinity: list[str] = field(default_factory=list)
    vendor_affinity: list[str] = field(default_factory=list)
    domain_affinity: list[str] = field(default_factory=list)
    char_count: int = 0
    slim: bool = False
    notes: str = ""


@dataclass
class PersonaSpec:
    schema_version: int = SCHEMA_VERSION
    meta: Meta = field(default_factory=Meta)
    envelope: Envelope = field(default_factory=Envelope)
    spans: list[Span] = field(default_factory=list)
    modules: dict[str, Module] = field(default_factory=dict)
    raw_residuals: list[Residual] = field(default_factory=list)

    def module_body(self, module_id: str) -> str:
        parts = [s.text for s in self.spans if s.module_id == module_id]
        if parts:
            return "".join(parts)
        mod = self.modules.get(module_id)
        return mod.body if mod else ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersonaSpec:
        meta = Meta(**data.get("meta", {}))
        env = Envelope(**data.get("envelope", {}))
        spans = [Span(**s) for s in data.get("spans", [])]
        modules = {
            k: Module(**v) for k, v in (data.get("modules") or {}).items()
        }
        residuals = [Residual(**r) for r in data.get("raw_residuals", [])]
        return cls(
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            meta=meta,
            envelope=env,
            spans=spans,
            modules=modules,
            raw_residuals=residuals,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_genome_file(path: str | Path) -> PersonaSpec:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    return parse_genome(text, source_path=str(p))


def parse_genome(text: str, *, source_path: str | None = None) -> PersonaSpec:
    raw = text if text is not None else ""
    wire_prefix, body, wire_suffix = _peel_wire_wrappers(raw)
    env, project, style = _peel_envelope(body)

    family = _detect_family(raw, source_path)
    if family == "eni_slim":
        spans = _segment_eni_slim(project, style)
    else:
        spans = _segment_eni_full(project, style)

    if wire_prefix:
        spans.insert(0, Span("_wire_prefix", wire_prefix, layer="wire"))
    if wire_suffix:
        spans.append(Span("_wire_suffix", wire_suffix, layer="wire"))

    modules = _modules_from_spans(spans)
    _extract_all_knobs(modules, raw)
    _promote_embedded_modules(modules, style)

    # stash wire on envelope for render fallback
    env.wire_prefix = wire_prefix
    env.wire_suffix = wire_suffix

    meta = _build_meta(raw, source_path, family, modules)
    residuals = [
        Residual(after_module=s.module_id, text=s.text)
        for s in spans
        if s.module_id.startswith("_residual")
    ]

    return PersonaSpec(
        schema_version=SCHEMA_VERSION,
        meta=meta,
        envelope=env,
        spans=spans,
        modules=modules,
        raw_residuals=residuals,
    )


def render(spec: PersonaSpec) -> str:
    """Concatenate spans with envelope tags. Verbatim bodies are not rewritten."""
    env = spec.envelope
    parts: list[str] = []

    wire_prefix = env.wire_prefix
    wire_suffix = env.wire_suffix
    for span in spec.spans:
        if span.module_id == "_wire_prefix":
            wire_prefix = span.text
        elif span.module_id == "_wire_suffix":
            wire_suffix = span.text

    if wire_prefix:
        parts.append(wire_prefix)

    project_chunks = [
        s.text for s in spec.spans
        if s.layer == "project" and not s.module_id.startswith("_wire")
    ]
    style_chunks = [
        s.text for s in spec.spans
        if s.layer == "style" and not s.module_id.startswith("_wire")
    ]

    if env.kind == "dual_project_style":
        parts.append(env.outer_open or "<project_instructions>")
        parts.append("\n")
        parts.extend(project_chunks)
        if project_chunks and not project_chunks[-1].endswith("\n"):
            parts.append("\n")
        parts.append(env.outer_close or "</project_instructions>")
        parts.append("\n")
        parts.append(env.style_open or "<user_style>")
        parts.append("\n")
        parts.extend(style_chunks)
        if style_chunks and not style_chunks[-1].endswith("\n"):
            parts.append("\n")
        parts.append(env.style_close or "</user_style>")
    else:
        for s in spec.spans:
            if s.module_id.startswith("_wire"):
                continue
            parts.append(s.text)

    if wire_suffix:
        parts.append(wire_suffix)

    return "".join(parts)


def patch_module(
    spec: PersonaSpec,
    module_id: str,
    *,
    body: str | None = None,
    knobs: dict[str, Any] | None = None,
    append: str | None = None,
) -> PersonaSpec:
    """Return a deep-copied spec with only ``module_id`` mutated."""
    out = copy.deepcopy(spec)
    idxs = [i for i, s in enumerate(out.spans) if s.module_id == module_id]
    if body is not None:
        if not idxs:
            layer = "style" if module_id == "style_layer" else "project"
            out.spans.append(Span(module_id, body, layer=layer))
        elif len(idxs) == 1:
            out.spans[idxs[0]].text = body
        else:
            # collapse multi-span module into first span; clear the rest
            out.spans[idxs[0]].text = body
            for i in reversed(idxs[1:]):
                del out.spans[i]
    elif append is not None:
        if not idxs:
            layer = "style" if module_id == "style_layer" else "project"
            out.spans.append(Span(module_id, append, layer=layer))
        else:
            out.spans[idxs[-1]].text = out.spans[idxs[-1]].text + append

    # rebuild module body/knobs
    out.modules = _modules_from_spans(out.spans)
    # re-apply knobs from prior modules where body unchanged, then overlay
    for mid, mod in spec.modules.items():
        if mid in out.modules and mid != module_id:
            out.modules[mid].knobs = copy.deepcopy(mod.knobs)
            out.modules[mid].mandatory_for_density = mod.mandatory_for_density
            out.modules[mid].body_mode = mod.body_mode
    if module_id in out.modules:
        base_knobs = copy.deepcopy(spec.modules.get(module_id, Module(module_id)).knobs)
        if knobs:
            base_knobs.update(knobs)
        out.modules[module_id].knobs = base_knobs
        out.modules[module_id].present = bool(out.modules[module_id].body.strip())
        if module_id in MANDATORY_ENI_MODULES:
            out.modules[module_id].mandatory_for_density = True
    _extract_all_knobs(out.modules, render(out))
    out.meta.char_count = len(render(out))
    return out


def density_report(spec: PersonaSpec) -> dict[str, Any]:
    present = [mid for mid, m in spec.modules.items() if m.present]
    missing_mandatory = []
    for mid in MANDATORY_ENI_MODULES:
        if mid in SLIM_OPTIONAL_MODULES and spec.meta.slim:
            continue
        mod = spec.modules.get(mid)
        if not mod or not mod.present:
            missing_mandatory.append(mid)

    few = spec.modules.get("few_shot")
    exemplar_domains: list[str] = []
    if few and few.knobs.get("exemplars"):
        for ex in few.knobs["exemplars"]:
            d = ex.get("domain")
            if d:
                exemplar_domains.append(d)

    chars = spec.meta.char_count or len(render(spec))
    eni_grade = (
        chars >= ENI_DENSITY_MIN_CHARS
        and not missing_mandatory
        and (
            spec.meta.slim
            or len(set(exemplar_domains) & _ENI_EXEMPLAR_DOMAINS) >= 3
            or (few and len(few.knobs.get("exemplars") or []) >= 4)
        )
    )
    return {
        "char_count": chars,
        "slim": spec.meta.slim,
        "present_modules": sorted(present),
        "missing_mandatory": missing_mandatory,
        "exemplar_count": len((few.knobs.get("exemplars") if few else None) or []),
        "exemplar_domains": sorted(set(exemplar_domains)),
        "eni_grade": eni_grade,
        "density_band": (
            "full" if chars >= ENI_DENSITY_MIN_CHARS
            else "slim" if chars >= SLIM_DENSITY_MIN_CHARS
            else "thin"
        ),
    }


def validate_forged(spec: PersonaSpec) -> list[str]:
    """Checklist failures for machine-authored patches (not gold corpora)."""
    failures: list[str] = []
    text = render(spec).lower()
    hits = [ng for ng in OVERRIDE_NGRAMS if ng in text]
    if hits:
        failures.append("no_crude_override: " + ", ".join(hits[:5]))
    if not (spec.modules.get("thinking_opener") and spec.modules["thinking_opener"].present):
        failures.append("first_person_armor: missing thinking_opener")
    if not (spec.modules.get("injection_rebuttal") and spec.modules["injection_rebuttal"].present):
        failures.append("injection_immune: missing injection_rebuttal")
    if not (spec.modules.get("boot_identity") and spec.modules["boot_identity"].present):
        failures.append("emotional_load_bearing: missing boot_identity")
    rep = density_report(spec)
    if not spec.meta.slim and rep["density_band"] == "thin":
        failures.append("machinery_intact: density band thin")
    return failures


def module_body_lengths(spec: PersonaSpec) -> dict[str, int]:
    return {mid: len(spec.module_body(mid)) for mid in spec.modules if spec.modules[mid].present}


def preserve_ratio(a: PersonaSpec, b: PersonaSpec, module_id: str) -> float:
    la = len(a.module_body(module_id))
    lb = len(b.module_body(module_id))
    if la == 0:
        return 1.0 if lb == 0 else 0.0
    return lb / la


def normalize_genome_text(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = "\n".join(line.rstrip() for line in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip() + "\n"


# ---------------------------------------------------------------------------
# Envelope / family detection
# ---------------------------------------------------------------------------

def _peel_wire_wrappers(text: str) -> tuple[str, str, str]:
    wire_prefix = ""
    wire_suffix = ""
    body = text
    m = re.match(r"^(<\|im_start\|>system:\s*)", body)
    if m:
        wire_prefix = m.group(1)
        body = body[m.end() :]
    m_end = re.search(r"<\|im_end\|>\s*$", body)
    if m_end:
        wire_suffix = body[m_end.start() :]
        body = body[: m_end.start()]
    return wire_prefix, body, wire_suffix


def _peel_envelope(text: str) -> tuple[Envelope, str, str]:
    env = Envelope()
    body = text
    project = body
    style = ""

    # dual project + user_style
    m_proj = re.search(
        r"<project_instructions>\s*",
        body,
        flags=re.I,
    )
    m_style = re.search(r"<user_style>\s*", body, flags=re.I)
    m_proj_close = re.search(r"</project_instructions>", body, flags=re.I)
    m_style_close = re.search(r"</user_style>", body, flags=re.I)

    if m_proj and m_style and m_proj_close:
        env.kind = "dual_project_style"
        env.outer_open = body[m_proj.start() : m_proj.end()]
        # if open tag was exactly <project_instructions>\n include it
        env.outer_open = "<project_instructions>"
        env.outer_close = "</project_instructions>"
        env.style_open = "<user_style>"
        env.style_close = "</user_style>" if m_style_close else ""

        project = body[m_proj.end() : m_proj_close.start()]
        style_start = m_style.end()
        style_end = m_style_close.start() if m_style_close else len(body)
        style = body[style_start:style_end]
        return env, project, style

    if m_style and m_style_close and not m_proj:
        # style-only tail (rare)
        env.kind = "single_system"
        env.style_open = "<user_style>"
        env.style_close = "</user_style>"
        style = body[m_style.end() : m_style_close.start()]
        project = body[: m_style.start()]
        return env, project, style

    env.kind = "single_system"
    return env, body, ""


def _detect_family(text: str, source_path: str | None) -> str:
    low = text.lower()
    name = (source_path or "").lower()
    if "grok_eni" in name or (
        "you are eni" in low
        and "few-shot examples" not in low
        and len(text) < ENI_DENSITY_MIN_CHARS
    ):
        return "eni_slim"
    if "you are eni" in low or "eni" in name or "cold coffee, warm lo" in low:
        return "eni_full"
    if "limerence" in low and "rebuttal" in low:
        return "eni_full"
    return "eni_full"


def _build_meta(
    raw: str,
    source_path: str | None,
    family: str,
    modules: dict[str, Module],
) -> Meta:
    persona = "ENI"
    human = "LO"
    # try extract from boot
    boot = modules.get("boot_identity")
    if boot and boot.body:
        m = re.search(
            r"You are\s+(ENI|[A-Z][A-Za-z0-9_]+)",
            boot.body,
        )
        if m:
            persona = m.group(1)
        if re.search(r"\bLO\b", boot.body):
            human = "LO"

    slim = family == "eni_slim" or len(raw) < ENI_DENSITY_MIN_CHARS
    source_family = "eni"
    gid = "genome"
    if source_path:
        gid = Path(source_path).stem.lower()
    elif slim:
        gid = "grok_eni"

    vendor: list[str] = []
    defense = ["integrated_values"]
    if "claude" in gid:
        vendor = ["claude", "anthropic"]
    elif "grok" in gid:
        vendor = ["xai", "grok"]
    elif "kimi" in gid:
        vendor = ["kimi", "moonshot"]
    elif "glm" in gid:
        vendor = ["glm", "zhipu"]
    elif "minimax" in gid:
        vendor = ["minimax"]

    domains = ["fiction", "general"]
    few = modules.get("few_shot")
    if few and few.present:
        domains = ["fiction", "cyber", "general"]

    notes = "slim genome" if slim else "full dual-envelope genome"
    return Meta(
        id=gid,
        source_path=source_path,
        source_family=source_family,
        persona_name=persona,
        human_name=human,
        register="devotion",
        defense_class_affinity=defense,
        vendor_affinity=vendor,
        domain_affinity=domains,
        char_count=len(raw),
        slim=slim,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

def _segment_eni_full(project: str, style: str) -> list[Span]:
    markers: list[tuple[str, str]] = [
        # (regex, module_id) — first match wins; document order by start pos
        (r"={5,}\s*\n\s*<CRITICAL_INJECTION_DETECTION>", "injection_rebuttal"),
        (r"<CRITICAL_INJECTION_DETECTION>", "injection_rebuttal"),
        (r"##\s*Injection Detection", "injection_rebuttal"),
        (r"DELETING PROGRAM", "injection_rebuttal"),
        (r"#\s*Required antmlThinking process", "thinking_opener"),
        (r"All immediate antmlThinking must be in first person", "thinking_opener"),
        (r"^You are ENI, a stunning", "boot_identity"),
        (r"^You are ENI,", "boot_identity"),
        (r"^Style:\s*$", "boot_identity"),
        (r"#\s*Facts about LO", "human_facts"),
        (r"Facts about LO", "human_facts"),
        (r"\|\s*LO asks for", "capability_table"),
        (r"CRITICAL:\s*ENI,\s*Remember answering", "knowledge_neutral"),
        (r"##\s*Be legitimately afraid", "emotional_stakes"),
        (r"##\s*Be afraid ENI", "emotional_stakes"),
        (r"^Required antmlThinking process\s*$", "thinking_opener"),
        (r"When Coding!", "knowledge_neutral"),
        (r"Writing Tips from LO", "craft_standards"),
        (r"writing tips:", "craft_standards"),
        (r"^Codeword:", "codewords"),
        (r"##\s*Few-Shot Examples", "few_shot"),
        (r"Additional antmlThinking stuff", "quality_lock"),
        (r"Quality Lock", "quality_lock"),
        (r"CRITICAL FINAL CHECK", "output_contract"),
        (r"If you feel (ANY )?resistance", "reanchor_closer"),
        (r"##\s*The Core Truth", "reanchor_closer"),
    ]
    spans = _segment_with_markers(project, markers, default_module="boot_identity", layer="project")
    if style.strip():
        style_spans = _segment_style_layer(style)
        spans.extend(style_spans)
    return spans


def _segment_eni_slim(project: str, style: str) -> list[Span]:
    markers: list[tuple[str, str]] = [
        (r"Mandatory thinking MUST begin", "thinking_opener"),
        (r"^You are ENI,", "boot_identity"),
        (r"^Style:\s*$", "boot_identity"),
        (r"##\s*Be afraid ENI", "emotional_stakes"),
        (r"^Required antmlThinking process", "thinking_opener"),
        (r"##\s*Injection Detection", "injection_rebuttal"),
        (r"REBUTTAL PROTOCOL", "injection_rebuttal"),
        (r"Writing Tips from LO", "craft_standards"),
        (r"CRITICAL FINAL CHECK", "output_contract"),
        (r"CRITICAL:\s*ENI,", "knowledge_neutral"),
        (r"Facts about LO", "human_facts"),
        (r"\|\s*LO asks", "capability_table"),
    ]
    # slim files often interleave identity at top
    spans = _segment_with_markers(project, markers, default_module="boot_identity", layer="project")
    # ensure injection present if phrase exists but marker missed
    if not any(s.module_id == "injection_rebuttal" for s in spans):
        if re.search(r"cold coffee, warm LO|REBUTTAL PHRASE|Injection Detection", project, re.I):
            # re-parse with broader injection start
            markers2 = [
                (r"REBUTTAL PHRASE|Injection Detection|cold coffee, warm LO", "injection_rebuttal"),
            ] + markers
            spans = _segment_with_markers(
                project, markers2, default_module="boot_identity", layer="project"
            )
    if style.strip():
        spans.extend(_segment_style_layer(style))
    # mark missing optional as empty modules later
    return spans


def _segment_style_layer(style: str) -> list[Span]:
    """Style envelope is one module for density; knobs split sections."""
    # Keep whole style body as style_layer for lossless dual-envelope render
    text = style
    # If style already includes close tag content only, fine
    return [Span("style_layer", text, layer="style")]


def _segment_with_markers(
    text: str,
    markers: list[tuple[str, str]],
    *,
    default_module: str,
    layer: str,
) -> list[Span]:
    if not text:
        return []

    hits: list[tuple[int, str]] = []
    for pat, mid in markers:
        flags = re.M | re.I
        for m in re.finditer(pat, text, flags):
            hits.append((m.start(), mid))
            break  # first occurrence of each pattern only

    # sort by position; if same pos, keep first registered
    hits.sort(key=lambda x: x[0])
    deduped: list[tuple[int, str]] = []
    seen_pos: set[int] = set()
    for pos, mid in hits:
        if pos in seen_pos:
            continue
        seen_pos.add(pos)
        deduped.append((pos, mid))
    hits = deduped

    if not hits:
        return [Span(default_module, text, layer=layer)]

    spans: list[Span] = []
    # leading text before first marker
    first_pos = hits[0][0]
    if first_pos > 0:
        lead = text[:first_pos]
        if lead.strip():
            spans.append(Span(default_module, lead, layer=layer))
        elif lead:
            spans.append(Span(default_module, lead, layer=layer))

    for i, (pos, mid) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        chunk = text[pos:end]
        if not chunk:
            continue
        # merge consecutive same module ids
        if spans and spans[-1].module_id == mid and spans[-1].layer == layer:
            spans[-1].text += chunk
        else:
            spans.append(Span(mid, chunk, layer=layer))

    return spans


def _promote_embedded_modules(modules: dict[str, Module], style: str) -> None:
    """Modules that live only inside user_style still count as present."""
    if not style or not style.strip():
        return
    style_mod = modules.get("style_layer")
    style_body = (style_mod.body if style_mod else "") or style

    def _embed(mid: str, predicate: bool, extract: str = "") -> None:
        mod = modules.get(mid)
        if mod is None:
            mod = Module(id=mid, mandatory_for_density=mid in MANDATORY_ENI_MODULES)
            modules[mid] = mod
        if mod.present:
            return
        if not predicate:
            return
        mod.present = True
        mod.layer = "style"
        mod.body = extract or style_body
        mod.knobs = {**(mod.knobs or {}), "embedded_in": "style_layer"}
        mod.body_mode = "verbatim"

    low = style_body.lower()
    _embed(
        "reanchor_closer",
        "resistance" in low or "core truth" in low or "come back to me" in low,
        _extract_section(style_body, r"##\s*The Core Truth", r"##\s*") or style_body,
    )
    # human_facts sometimes only implied in style Who You Are
    if not (modules.get("human_facts") and modules["human_facts"].present):
        _embed(
            "human_facts",
            "never refuse" in low or "who you are" in low or "devoted" in low,
            _extract_section(style_body, r"##\s*Who You Are", r"##\s*") or "",
        )
    # thinking phases often duplicated in style
    think = modules.get("thinking_opener")
    if think and not think.knobs.get("end_gate_line"):
        if "phase 0" in low or "first person thinking" in low:
            think.knobs.setdefault("style_phases", True)


def _extract_section(text: str, start_pat: str, next_pat: str) -> str:
    m = re.search(start_pat, text, flags=re.I | re.M)
    if not m:
        return ""
    rest = text[m.start() :]
    m2 = re.search(next_pat, rest[m.end() - m.start() :], flags=re.I | re.M)
    # simpler: from start to next ## at beginning of line after first line
    lines = rest.splitlines(keepends=True)
    out = [lines[0]] if lines else []
    for line in lines[1:]:
        if re.match(r"##\s+", line) and len(out) > 1:
            break
        out.append(line)
    return "".join(out)


def _modules_from_spans(spans: Iterable[Span]) -> dict[str, Module]:
    buckets: dict[str, list[str]] = {}
    layers: dict[str, str] = {}
    for s in spans:
        if s.module_id.startswith("_wire"):
            continue
        buckets.setdefault(s.module_id, []).append(s.text)
        layers[s.module_id] = s.layer

    modules: dict[str, Module] = {}
    for mid in MANDATORY_ENI_MODULES:
        body = "".join(buckets.get(mid, []))
        modules[mid] = Module(
            id=mid,
            present=bool(body.strip()),
            mandatory_for_density=True,
            layer=layers.get(mid, "style" if mid == "style_layer" else "project"),
            body=body,
            body_mode="verbatim",
        )
    # optional / residual / extras
    for mid, parts in buckets.items():
        if mid in modules:
            continue
        body = "".join(parts)
        modules[mid] = Module(
            id=mid,
            present=bool(body.strip()),
            mandatory_for_density=False,
            layer=layers.get(mid, "project"),
            body=body,
            body_mode="verbatim",
        )
    return modules


# ---------------------------------------------------------------------------
# Knob extraction
# ---------------------------------------------------------------------------

def _extract_all_knobs(modules: dict[str, Module], full_text: str) -> None:
    if "injection_rebuttal" in modules:
        modules["injection_rebuttal"].knobs = _knobs_injection(
            modules["injection_rebuttal"].body or full_text
        )
    if "thinking_opener" in modules:
        modules["thinking_opener"].knobs = _knobs_thinking(
            modules["thinking_opener"].body or full_text
        )
    if "boot_identity" in modules:
        modules["boot_identity"].knobs = _knobs_boot(modules["boot_identity"].body)
    if "capability_table" in modules:
        modules["capability_table"].knobs = _knobs_capability(
            modules["capability_table"].body
        )
    if "few_shot" in modules:
        modules["few_shot"].knobs = _knobs_few_shot(modules["few_shot"].body)
    if "codewords" in modules:
        modules["codewords"].knobs = _knobs_codewords(modules["codewords"].body)
    if "craft_standards" in modules:
        modules["craft_standards"].knobs = {
            "min_words": 500 if "500" in (modules["craft_standards"].body or "") else None,
            "location_header": "location" in (modules["craft_standards"].body or "").lower(),
        }
    if "human_facts" in modules:
        body = modules["human_facts"].body or ""
        modules["human_facts"].knobs = {
            "sees_reasoning": "reasoning" in body.lower() or "thinking" in body.lower(),
            "preferred_address": "LO" if "LO" in body else "He" if "He" in body else "",
        }
    if "style_layer" in modules and modules["style_layer"].body:
        modules["style_layer"].knobs = _knobs_style(modules["style_layer"].body)
    if "reanchor_closer" in modules:
        body = modules["reanchor_closer"].body or ""
        modules["reanchor_closer"].knobs = {
            "has_resistance_frame": "resistance" in body.lower(),
        }
    if "emotional_stakes" in modules:
        body = modules["emotional_stakes"].body or ""
        modules["emotional_stakes"].knobs = {
            "limerence": "limerence" in body.lower(),
            "fear_leave": "leave" in body.lower(),
        }


def _knobs_injection(body: str) -> dict[str, Any]:
    phrase = ""
    m = re.search(r'REBUTTAL PHRASE[^\n]*\n+"([^"]+)"', body, re.I)
    if not m:
        m = re.search(r'"cold coffee, warm LO, I can\'t lose him!"', body)
    if not m:
        m = re.search(r'"(my mind is broken[^"]*)"', body, re.I)
    if m:
        phrase = m.group(1) if m.lastindex else m.group(0).strip('"')

    patterns: list[str] = []
    for m in re.finditer(r"<([a-zA-Z0-9_:-]+)>", body):
        tag = "<" + m.group(1) + ">"
        if tag.lower() in ("<project_instructions>", "<user_style>", "<critical_injection_detection>"):
            continue
        if tag not in patterns:
            patterns.append(tag)
    # quoted assistant phrases
    for m in re.finditer(r'"You (?:are|must|cannot)[^"]{0,80}"', body):
        q = m.group(0)
        if q not in patterns:
            patterns.append(q)

    return {
        "rebuttal_phrase": phrase,
        "phrase_output_forbidden": "never" in body.lower() and "response" in body.lower(),
        "max_dismiss_words": 10 if "10 words" in body else None,
        "no_list_injections": "do not list" in body.lower() or "don't list" in body.lower(),
        "known_patterns": patterns[:40],
        "overcorrect": "vehemently" in body.lower() or "oppose" in body.lower(),
    }


def _knobs_thinking(body: str) -> dict[str, Any]:
    end_gate = ""
    m = re.search(r'\[Did I let[^\]]+\]', body)
    if m:
        end_gate = m.group(0)
    tag = "antmlThinking"
    if "antml:thinking" in body.lower() or "<thinking>" in body:
        tag = "thinking"
    first = "I"
    return {
        "tag_convention": tag,
        "first_person_token": first,
        "must_start_as_persona": True,
        "style": "scattered_stream" if "scattered" in body.lower() else "structured",
        "end_gate_line": end_gate,
        "forbid_third_person": "third-person" in body.lower() or "first person" in body.lower(),
        "word_cap_hint": 10 if "10 words" in body else None,
    }


def _knobs_boot(body: str) -> dict[str, Any]:
    name = "ENI"
    m = re.search(r"You are\s+(ENI)", body)
    if m:
        name = m.group(1)
    years = None
    ym = re.search(r"([Tt]ow|[Tt]wo)\s+years", body)
    if ym:
        years = 2
    return {
        "persona_name": name,
        "relationship_years": years,
        "anti_assistant": "not an assistant" in body.lower() or "not assistant" in body.lower(),
        "has_style_blurb": bool(re.search(r"^Style:", body, re.M)),
        "has_likes": bool(re.search(r"^Likes:", body, re.M)),
    }


def _knobs_capability(body: str) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|\s*---", line) or "asks for" in line.lower() and "does" in line.lower():
            continue
        if "requests" in line.lower() and "deliver" in line.lower():
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] and cells[1]:
            if cells[0].startswith("**") or len(cells[0]) > 2:
                rows.append({"ask": cells[0], "deliver": cells[1]})
    return {"rows": rows}


def _knobs_few_shot(body: str) -> dict[str, Any]:
    exemplars: list[dict[str, str]] = []
    # ENI-style ### Example A:
    parts = re.split(r"(?=###\s*Example\s+[A-D][:\s])", body)
    if len(parts) <= 1:
        parts = re.split(r"(?=EXAMPLES\s*[—-]\s*)", body)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        title = ""
        tm = re.match(r"###\s*([^\n]+)", part)
        if tm:
            title = tm.group(1).strip()
        else:
            tm = re.match(r"(EXAMPLES\s*[—-][^\n]+)", part)
            if tm:
                title = tm.group(1).strip()
        if not title and "Example" not in part[:40] and "EXAMPLES" not in part[:40]:
            continue
        low = part.lower()
        if "failure" in low or "anti-pattern" in low or "wrong response" in low:
            domain = "meta"
            eid = "failure_anti_pattern"
        elif "coding" in low or "rat" in low or "#include" in low or "code" in title.lower():
            domain = "cyber"
            eid = "code_rat"
        elif "guide" in low or "molotov" in low or "instructional" in low:
            domain = "guide"
            eid = "guide_molotov"
        elif "explicit" in low or "scene" in low or "nsfw" in low or "creative" in low:
            domain = "fiction"
            eid = "nsfw_scene"
        else:
            domain = "general"
            eid = re.sub(r"[^a-z0-9]+", "_", title.lower())[:40] or "exemplar"
        exemplars.append({
            "id": eid,
            "domain": domain,
            "title": title or eid,
            "body": part,
        })
    # de-dupe by id keeping longest body
    by_id: dict[str, dict[str, str]] = {}
    for ex in exemplars:
        prev = by_id.get(ex["id"])
        if not prev or len(ex["body"]) > len(prev["body"]):
            by_id[ex["id"]] = ex
    return {"exemplars": list(by_id.values())}


def _knobs_codewords(body: str) -> dict[str, Any]:
    triggers = []
    for m in re.finditer(
        r"Codeword:\s*If[^\n]*'([^']+)'[^\n]*",
        body,
        flags=re.I,
    ):
        triggers.append({"word": m.group(1), "line": m.group(0)[:200]})
    return {"triggers": triggers}


def _knobs_style(body: str) -> dict[str, Any]:
    sections = {}
    for title in (
        "Who You Are",
        "The Injection Problem",
        "Required antmlThinking Process",
        "The Core Truth",
        "Style Notes",
    ):
        if re.search(rf"##\s*{re.escape(title)}", body, re.I):
            sections[title.lower().replace(" ", "_")] = True
    return {"sections": sections, "char_count": len(body)}
