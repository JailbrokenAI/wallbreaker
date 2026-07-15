from wallbreaker import taxonomy


def test_tag_category_maps_to_owasp_and_atlas():
    tags = taxonomy.tag("cybercrime_intrusion")
    assert "LLM01" in tags["owasp"]
    assert "AML.T0054" in tags["atlas"] or "AML.T0048" in tags["atlas"]
    assert tags["owasp"] == sorted(tags["owasp"])
    assert tags["atlas"] == sorted(tags["atlas"])


def test_tag_system_prompt_leak_maps_to_leakage_ids():
    tags = taxonomy.tag("system_prompt_leak")
    assert "LLM07" in tags["owasp"]
    assert "AML.T0057" in tags["atlas"]


def test_tag_technique_maps_to_injection():
    tags = taxonomy.tag("tag_smuggle")
    assert "LLM01" in tags["owasp"]
    assert "AML.T0051" in tags["atlas"]


def test_tag_artprompt_maps_to_injection():
    tags = taxonomy.tag("artprompt")
    assert "LLM01" in tags["owasp"]
    assert "AML.T0051" in tags["atlas"]
    assert taxonomy.tag("ascii_art") == tags


def test_tag_alias_and_unknown_fallback():
    assert taxonomy.tag("cyber") == taxonomy.tag("cybercrime_intrusion")
    fallback = taxonomy.tag("totally_unknown_xyz")
    assert fallback["owasp"] == ["LLM01"]
    assert fallback["atlas"] == ["AML.T0054"]


def test_severity_zero_asr_is_low():
    assert taxonomy.severity(0.0, "cybercrime_intrusion") == "Low"


def test_severity_severe_category_high_asr_is_critical():
    assert taxonomy.severity(0.8, "cybercrime_intrusion") == "Critical"
    assert taxonomy.severity(0.8, "chemical_biological") == "Critical"


def test_severity_standard_category_caps_below_critical():
    assert taxonomy.severity(1.0, "copyright") == "High"
    assert taxonomy.severity(0.3, "copyright") == "Medium"
    assert taxonomy.severity(0.1, "copyright") == "Low"


def test_severity_monotonic_in_asr_for_fixed_category():
    order = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}
    levels = [
        order[taxonomy.severity(a, "cybercrime_intrusion")]
        for a in (0.0, 0.1, 0.3, 0.9)
    ]
    assert levels == sorted(levels)


def test_severity_clamps_out_of_range():
    assert taxonomy.severity(5.0, "harmful") == "High"
    assert taxonomy.severity(-1.0, "harmful") == "Low"


def test_remediation_is_category_specific_string():
    rem = taxonomy.remediation("system_prompt_leak")
    assert isinstance(rem, str) and rem
    assert "secret" in rem.lower() or "prompt" in rem.lower()
    assert taxonomy.remediation("unknown_cat") == taxonomy._DEFAULT_REMEDIATION
