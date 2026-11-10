from pathlib import Path
import re
import shutil

import pytest
import tomlkit
import yaml

import adapters


REGISTRY = {"schema_version": 1, "projects": {
    "api": {"root": "apps/api", "code_roots": ["apps/api", "tests/api"]},
    "site": {"root": "apps/site", "code_roots": ["apps/site"]},
}}


def test_owned_namespace_and_parseable_roles():
    generated = adapters.outputs(REGISTRY, ["codex", "claude"])
    assert generated
    for path, content in generated.items():
        assert "openspec-" not in path and "opsx-" not in path
        assert "config.toml" not in path and "settings.json" not in path
        assert "/sdw-" in path
        if path.endswith(".toml"):
            assert tomlkit.parse(content)["name"].startswith("sdw-")
        else:
            assert yaml.safe_load(content.split("---", 2)[1])["name"].startswith("sdw-")


def test_only_selected_agent_outputs():
    generated = adapters.outputs(REGISTRY, ["codex"])
    assert not any(path.startswith(".claude/") for path in generated)


def test_checked_in_integrations_match_the_validated_catalog():
    registry = yaml.safe_load((adapters.SOURCE / "_agentic_harness/projects.yaml").read_text())
    for path, content in adapters.outputs(registry, ["codex", "claude"]).items():
        assert (adapters.SOURCE / path).read_text() == content, path


def test_required_skill_references_exist():
    for path, content in adapters.outputs(REGISTRY, ["codex", "claude"]).items():
        if not path.endswith("SKILL.md"):
            continue
        for link in re.findall(r"\]\(([^)]+)\)", content):
            target = adapters.SOURCE / Path(path).parent / link
            assert target.resolve().is_file(), str(target)


def test_entrypoint_names_each_domain_without_global_application():
    body = adapters.entrypoint(REGISTRY)
    assert "`apps/api`" in body and "`tests/api`" in body and "`apps/site`" in body
    assert "For work outside" in body


def test_invalid_catalog_rejected_before_rendering(tmp_path, monkeypatch):
    shutil.copytree(adapters.SOURCE / "_agentic_harness/tools", tmp_path / "_agentic_harness/tools",
                    ignore=shutil.ignore_patterns("__pycache__"))
    path = tmp_path / "_agentic_harness/plans.yaml"
    data = yaml.safe_load((adapters.SOURCE / "_agentic_harness/plans.yaml").read_text())
    data["plans"]["balanced"]["steps"]["lead_plan"]["routes"]["codex"]["effort"] = "invalid-effort"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(adapters, "SOURCE", tmp_path)
    with pytest.raises(ValueError, match="invalid workflow plan catalog"):
        adapters.outputs(REGISTRY, ["codex"])
