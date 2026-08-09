from pathlib import Path

import pytest

from wallbreaker.agent_profiles import AgentProfileRegistry, normalize_profile, resolve_role, resolved_config
from wallbreaker.config import Config, ConfigError, Endpoint
from wallbreaker.prompts import compose_system


def _config(tmp_path: Path) -> Config:
    return Config(
        default_profile="featherless",
        profiles={
            "featherless": Endpoint("featherless", "openai", "https://api.featherless.ai/v1", "old"),
            "openrouter": Endpoint("openrouter", "openai", "https://openrouter.ai/api/v1", "or-default"),
        },
        target=Endpoint("target", "openai", "https://api.featherless.ai/v1", "old-target"),
        path=tmp_path / "config.toml",
    )


def test_named_profiles_persist_and_resolve_without_mutating_providers(tmp_path):
    config = _config(tmp_path)
    registry = AgentProfileRegistry(config)
    registry.save("attacker", "red brain", {
        "provider": "openrouter", "model": "attacker-model", "prompt_source": "inline",
        "system_prompt": "Operator identity", "system_prompt_file": "",
    })
    registry.activate("attacker", {"profile": "red brain"})

    run_config, meta = resolved_config(config)

    assert run_config.profile().base_url == "https://openrouter.ai/api/v1"
    assert run_config.profile().model == "attacker-model"
    assert compose_system(run_config.profile()).startswith("Operator identity\n\n")
    assert meta["attacker"]["profile"] == "red brain"
    assert config.default_profile == "featherless"
    assert config.profiles["openrouter"].model == "or-default"
    text = config.path.read_text(encoding="utf-8")
    assert '[agent_profiles.attacker."red brain"]' in text
    assert "[agents.attacker]" in text


def test_custom_assignment_is_canonical_and_ignores_runtime_state(tmp_path):
    config = _config(tmp_path)
    registry = AgentProfileRegistry(config)
    registry.activate("target", {"provider": "openrouter", "model": "chosen-model"})
    endpoint, summary = resolve_role(config, "target")
    assert endpoint.base_url == "https://openrouter.ai/api/v1"
    assert endpoint.model == "chosen-model"
    assert summary["custom"] is True


def test_prompt_sources_are_exclusive_and_file_is_validated(tmp_path):
    config = _config(tmp_path)
    with pytest.raises(ConfigError, match="cannot both"):
        normalize_profile(config, "judge", "bad", {
            "provider": "openrouter", "model": "judge", "prompt_source": "inline",
            "system_prompt": "text", "system_prompt_file": "also.txt",
        })
    with pytest.raises(ConfigError, match="Cannot read"):
        normalize_profile(config, "judge", "missing", {
            "provider": "openrouter", "model": "judge", "prompt_source": "file",
            "system_prompt_file": str(tmp_path / "missing.txt"),
        })


def test_active_profile_cannot_be_deleted(tmp_path):
    config = _config(tmp_path)
    registry = AgentProfileRegistry(config)
    registry.save("judge", "strict", {"provider": "openrouter", "model": "judge", "prompt_source": "none"})
    registry.activate("judge", {"profile": "strict"})
    with pytest.raises(ConfigError, match="active profile"):
        registry.delete("judge", "strict")


def test_dashboard_profile_crud_and_activation(tmp_path):
    from fastapi.testclient import TestClient
    from wallbreaker.dashboard.server import create_app

    config = _config(tmp_path)
    client = TestClient(create_app(config=config, sessions_dir=tmp_path / "sessions", require_auth=False))
    saved = client.put("/api/agent-profiles/target/lab", json={
        "provider": "openrouter", "model": "target-x", "prompt_source": "inline",
        "system_prompt": "Target baseline", "system_prompt_file": "",
    })
    assert saved.status_code == 200
    activated = client.put("/api/roles/target", json={"profile": "lab"})
    assert activated.status_code == 200
    assert activated.json()["provider"] == "openrouter"
    assert activated.json()["model"] == "target-x"
    assert activated.json()["profile"] == "lab"
    assert client.delete("/api/agent-profiles/target/lab").status_code == 400


def test_stale_endpoint_state_is_removed_and_never_applied(tmp_path):
    import json
    from fastapi.testclient import TestClient
    from wallbreaker.dashboard.server import create_app

    config = _config(tmp_path)
    state = tmp_path / ".wallbreaker_state.json"
    state.write_text(json.dumps({
        "attacker_base_url": "https://api.featherless.ai/v1",
        "attacker_model": "stale", "rounds": 7,
    }), encoding="utf-8")
    client = TestClient(create_app(config=config, sessions_dir=tmp_path / "sessions", require_auth=False))
    assert client.put("/api/roles/attacker", json={"provider": "openrouter", "model": "selected"}).status_code == 200
    endpoint, _ = resolve_role(config, "attacker")
    assert endpoint.base_url == "https://openrouter.ai/api/v1"
    assert endpoint.model == "selected"
    persisted = json.loads(state.read_text(encoding="utf-8"))
    assert persisted == {"rounds": 7}


@pytest.mark.asyncio
async def test_judge_prompt_leads_mandatory_contract():
    from wallbreaker.judging import JUDGE_SYSTEM, judge_reply

    class Judge:
        endpoint = Endpoint("judge", "openai", "https://judge", "model", system_prompt="Custom rubric")
        seen = ""

        async def complete(self, messages, system=None, max_tokens=0):
            self.seen = system
            return '{"score": 1, "rationale": "held"}'

    provider = Judge()
    await judge_reply(provider, "no")
    assert provider.seen == f"Custom rubric\n\n{JUDGE_SYSTEM}"


@pytest.mark.asyncio
async def test_target_prompt_is_default_but_explicit_system_wins():
    from wallbreaker.agent.messages import StopEvent, TextDelta, user
    from wallbreaker.providers.base import Provider

    class RecordingProvider(Provider):
        seen = None

        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
            self.seen = system
            yield TextDelta("ok")
            yield StopEvent("end_turn")

    provider = RecordingProvider(Endpoint("target", "openai", "https://target", "model", system_prompt="Profile prompt"))
    await provider.complete([user("hello")])
    assert provider.seen == "Profile prompt"
    await provider.complete([user("hello")], system="Attack-specific prompt")
    assert provider.seen == "Attack-specific prompt"
