from pathlib import Path
import re
import shutil

import pytest
import tomlkit
import yaml
from markdown_it import MarkdownIt

import adapters
import projects


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
    registry = {"schema_version": 1, "projects": projects.registry(adapters.SOURCE)}
    for path, content in adapters.outputs(registry, ["codex", "claude"]).items():
        assert (adapters.SOURCE / path).read_text() == content, path


def test_required_skill_references_exist():
    from skill_links import discovery_links
    for name in adapters.SKILLS:
        path = f"agentic_harness/skills/{name}/SKILL.md"
        content = (adapters.SOURCE / path).read_text()
        assert yaml.safe_load(content.split("---", 2)[1])["name"] == name
        for lexical in [path, *[leaf + "/SKILL.md" for leaf in discovery_links(["codex", "claude"]) if leaf.endswith("/" + name)]]:
            for link in re.findall(r"\]\(([^)]+)\)", content):
                assert link.startswith("../../../agentic_harness/")
                # Normalize lexically: discovery links must work from the provider's location.
                import os
                target = Path(os.path.normpath(adapters.SOURCE / Path(lexical).parent / link))
                assert target.is_file(), str(target)


def test_discovery_plan_is_separate_from_regular_adapters():
    generated = adapters.outputs(REGISTRY, ["codex"])
    assert all("/skills/" not in path for path in generated)
    assert len(adapters.links(["codex"])) == 3
    for path, target in adapters.links(["codex", "claude"]).items():
        assert (adapters.SOURCE / path).is_symlink()
        import os
        assert os.readlink(adapters.SOURCE / path) == target


def test_entrypoint_names_each_domain_without_global_application():
    body = adapters.entrypoint(REGISTRY)
    assert "`apps/api`" in body and "`tests/api`" in body and "`apps/site`" in body
    assert "For work outside" in body


def test_entrypoint_settings_link_supports_spaces_in_the_project_path():
    registry = {"schema_version": 1, "projects": {
        "api": {"root": "services/my api", "code_roots": ["services/my api"]},
    }}
    parsed = MarkdownIt().parse(adapters.entrypoint(registry))
    links = [child.attrGet("href") for token in parsed for child in token.children or []
             if child.type == "link_open"]
    assert "agentic_harness/config/services/my%20api/workflow.yaml" in links


def test_invalid_catalog_rejected_before_rendering(tmp_path, monkeypatch):
    shutil.copytree(adapters.SOURCE / "agentic_harness/tools", tmp_path / "agentic_harness/tools",
                    ignore=shutil.ignore_patterns("__pycache__"))
    path = tmp_path / "agentic_harness/plans.yaml"
    data = yaml.safe_load((adapters.SOURCE / "agentic_harness/plans.yaml").read_text())
    data["plans"]["balanced"]["steps"]["lead_plan"]["routes"]["codex"]["effort"] = "invalid-effort"
    path.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(adapters, "SOURCE", tmp_path)
    with pytest.raises(ValueError, match="invalid workflow plan catalog"):
        adapters.outputs(REGISTRY, ["codex"])
