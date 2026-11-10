"""Offline intake/authority/original-ticket evidence and invariant risk checks."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

spec = importlib.util.spec_from_file_location("harness_test_intake", Path(__file__).resolve().parents[1] / "tools/intake.py")
intake = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = intake
spec.loader.exec_module(intake)
CHANGE = "26-11-09-901-workflow-contract"


def planning():
    return {"schema_version": 1, "mode": "planning", "project": "example", "change": CHANGE,
            "scope": ["agentic_harness/docs/queue.md"],
            "request": {"problem": "Preserve ownership during restart", "outcome": "A restart preserves state",
                        "acceptance": ["Interrupted writers are reconciled"]},
            "authorities": [{"source": "user:message-42", "project": "example", "change": CHANGE,
                             "scope": ["agentic_harness"], "actions": ["planning"]}], "ticket": None}


def evidence(tmp_path, record, *, observation_changes=None):
    payload = {field: record["ticket"][field] for field in intake.TICKET_FIELDS}
    observation = {"schema_version": 1, "kind": "observed-ticket", "verified": True,
                   "observed_at": datetime.now(timezone.utc).isoformat(), "ticket": payload}
    if observation_changes:
        observation.update(observation_changes)
    path = tmp_path / "evidence" / "ticket-original.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(observation).encode()
    path.write_bytes(data)
    record["ticket"]["evidence"] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
    return path


@pytest.fixture
def implementation(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    record = planning()
    record["mode"] = "implementation"
    record["scope"] = ["agentic_harness/tools/coordination.py"]
    record["authorities"][0]["actions"] = ["implementation"]
    proposal = f"component/openspec/changes/{CHANGE}/proposal.md"
    capability = f"component/openspec/changes/{CHANGE}/specs/harness-workspaces/spec.md"
    for link in (proposal, capability):
        path = root / link
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Synthetic contract\n")
    record["ticket"] = {"id": "127", "revision": "observed-ticket-revision-3", **deepcopy(record["request"]),
                        "scope": list(record["scope"]), "project": "example", "change": CHANGE,
                        "spec_links": [proposal, capability], "dependencies": [], "relationships": ["pull-request:128"]}
    (root / "component/openspec/config.yaml").write_text("schema: spec-driven\n")
    (root / "component/openspec/queue.yaml").write_text("queue: []\n")
    (root / "agentic_harness").mkdir()
    (root / "agentic_harness/projects.yaml").write_text(yaml.safe_dump({
        "schema_version": 1, "projects": {"example": {
            "root": "component", "queue": "component/openspec/queue.yaml",
            "code_roots": ["component", "agentic_harness"], "checks": [["true"]]}}}))
    evidence(tmp_path, record)
    return root, record


def test_planning_null_ticket_never_authorizes_writer_and_reuses_source():
    record = planning()
    normalized = intake.validate_intake(record)
    assert normalized["ticket"] is None
    assert normalized["allowed_actions"] == ["planning"]
    assert normalized["authorities"][0]["source"] == "user:message-42"
    assert intake.validate_intake(normalized) == normalized
    record["mode"] = "review"
    record["authorities"][0]["actions"] = ["review", "implementation"]
    reviewed = intake.validate_intake(record)
    assert reviewed["allowed_actions"] == ["review"]
    assert reviewed["ticket"] is None


def test_implementation_requires_selected_verified_ticket_and_scoped_authority(implementation):
    root, record = implementation
    normalized = intake.validate_intake(record, root)
    assert normalized["ticket"]["verified"]
    assert normalized["allowed_actions"] == ["implementation", "writer"]
    assert intake.validate_intake(normalized, root) == normalized
    assert normalized["risk"]["category"] == "high"
    record["ticket"] = None
    with pytest.raises(ValueError, match="selected bounded ticket"):
        intake.validate_intake(record, root)


@pytest.mark.parametrize("mutation,diagnostic", [
    (lambda r: r["authorities"].clear(), "authority sources"),
    (lambda r: r["authorities"][0].update(actions=["planning"]), "implementation action"),
    (lambda r: r["authorities"][0].update(project="different"), "project/change"),
    (lambda r: r["authorities"][0].update(scope=["docs"]), "bounded intake scope"),
    (lambda r: r["authorities"][0].update(source=""), "nonempty string"),
    (lambda r: r["ticket"].update(change="26-11-09-999-other-change"), "ticket project/change"),
    (lambda r: r["ticket"].update(scope=["another.py"]), "scope mismatch"),
    (lambda r: r["request"].update(outcome="New expanded outcome"), "stale for current intake"),
    (lambda r: r["request"].update(acceptance=["New acceptance"]), "stale for current intake"),
    (lambda r: r["ticket"].update(revision="new-unobserved-ticket-revision"), "stale or mismatched"),
    (lambda r: r["ticket"].update(dependencies=["038"]), "qualified full change IDs"),
    (lambda r: r["ticket"].update(spec_links=["other/openspec/changes/26-11-09-999-other-change/proposal.md"]), "owning change proposal"),
])
def test_missing_stale_mismatched_ticket_or_authority_rejected(implementation, mutation, diagnostic):
    root, record = implementation
    mutation(record)
    with pytest.raises(ValueError, match=diagnostic):
        intake.validate_intake(record, root)


@pytest.mark.parametrize("source", ["127", "#127", "issue:127", "branch:feat/127-harness", "feat/127-harness", "main", "origin/main", "refs/heads/custom", "https://github.com/example/repo/issues/127"])
def test_historical_issue_or_branch_never_establishes_action_authority(source):
    record = planning()
    record["authorities"][0]["source"] = source
    with pytest.raises(ValueError, match="context, not action authority"):
        intake.validate_intake(record)


@pytest.mark.parametrize("condition", ["missing", "changed", "unverified", "mismatched", "no_timezone", "invalid_json", "duplicate_keys", "internal", "alias"])
def test_original_ticket_reference_is_checked(implementation, tmp_path, condition):
    root, record = implementation
    path = Path(record["ticket"]["evidence"]["path"])
    if condition == "missing":
        path.unlink()
    elif condition == "changed":
        path.write_text(path.read_text() + " ")
    elif condition == "unverified":
        evidence(tmp_path, record, observation_changes={"verified": False})
    elif condition == "mismatched":
        evidence(tmp_path, record, observation_changes={"ticket": {"id": "999"}})
    elif condition == "no_timezone":
        evidence(tmp_path, record, observation_changes={"observed_at": "2026-11-09T12:00:00"})
    elif condition in {"invalid_json", "duplicate_keys"}:
        data = b"not JSON" if condition == "invalid_json" else b'{"verified":true,"verified":false}'
        path.write_bytes(data)
        record["ticket"]["evidence"]["sha256"] = hashlib.sha256(data).hexdigest()
    elif condition == "internal":
        new = root / "ticket.json"
        new.write_bytes(path.read_bytes())
        record["ticket"]["evidence"]["path"] = str(new)
    else:
        alias = tmp_path / "alias.json"
        alias.symlink_to(path)
        record["ticket"]["evidence"]["path"] = str(alias)
    with pytest.raises(ValueError):
        intake.validate_intake(record, root)


@pytest.mark.parametrize("paths,flags,category,expected_flags", [
    (["docs/design.md"], [], "low", {"documentation"}),
    (["assets/generated.svg"], ["mechanical"], "low", {"mechanical"}),
    (["src/parser.py"], [], "standard", set()),
    (["src/recovery/runner.py"], ["mechanical"], "high", {"recovery", "mechanical"}),
    (["src/schema/model.py"], [], "high", {"schema"}),
    (["src/security/tokens.py"], [], "high", {"security"}),
    (["docs/migration.md"], ["documentation"], "high", {"data_migration", "documentation"}),
    (["src/general.py"], ["uncertain"], "high", {"uncertain"}),
])
def test_risk_is_concrete_and_never_waives_two_fresh_lenses(paths, flags, category, expected_flags):
    risk = intake.classify_risk(paths, flags)
    assert risk["category"] == category
    assert expected_flags <= set(risk["flags"])
    assert risk["required_reviewers"] == 2
    assert risk["fresh_review_identities_required"] is True
    assert risk["automatic_model_upgrade"] is False
    assert risk["escalation_requires_explicit_authority"] is True


@pytest.mark.parametrize("policy", [
    {"required_reviewers": 1, "fresh_review_identities_required": True},
    {"required_reviewers": 2, "fresh_review_identities_required": False},
    {"required_reviewers": 2, "fresh_review_identities_required": True, "single_reviewer_exemption": "mechanical"},
])
def test_false_single_reviewer_exemption_rejected_even_for_documents(policy):
    record = planning()
    record["review_policy"] = policy
    with pytest.raises(ValueError, match="two fresh independent"):
        intake.validate_intake(record)


def test_ungranted_remote_actions_are_never_inferred_and_normalized_fields_cannot_spoof():
    record = planning()
    assert "publish" not in intake.validate_intake(record)["allowed_actions"]
    record["authorities"][0]["actions"].append("publish")
    assert "publish" in intake.validate_intake(record)["allowed_actions"]
    record["allowed_actions"] = ["planning", "implementation", "writer"]
    with pytest.raises(ValueError, match="allowed_actions"):
        intake.validate_intake(record)
    del record["allowed_actions"]
    record["risk"] = {"required_reviewers": 1}
    with pytest.raises(ValueError, match="classification"):
        intake.validate_intake(record)


@pytest.mark.parametrize("record", [None, [], {}, {"schema_version": True}])
def test_malformed_intake_errors_are_value_errors(record):
    with pytest.raises(ValueError):
        intake.validate_intake(record)


def test_path_and_flag_validation_fail_as_value_errors():
    record = planning()
    record["scope"] = ["../escape.py"]
    with pytest.raises(ValueError):
        intake.validate_intake(record)
    with pytest.raises(ValueError):
        intake.validate_intake(planning(), repository_root=123)
    with pytest.raises(ValueError, match="unknown risk flags"):
        intake.classify_risk(["README.md"], ["single-reviewer"])


def test_original_user_message_url_is_valid_authority_reference():
    record = planning()
    record["authorities"][0]["source"] = "https://chatgpt.com/c/authorizing-user-message"
    assert intake.validate_intake(record)["allowed_actions"] == ["planning"]


def test_original_ticket_scope_order_survives_normalized_revalidation(implementation, tmp_path):
    root, record = implementation
    record["scope"] = ["agentic_harness/tools/z.py", "agentic_harness/tools/a.py"]
    record["ticket"]["scope"] = list(record["scope"])
    record["ticket"]["spec_links"].reverse()
    evidence(tmp_path, record)
    normalized = intake.validate_intake(record, root)
    assert normalized["scope"] == sorted(record["scope"])
    assert intake.validate_intake(normalized, root) == normalized


def root_project(root, record):
    (root / "component/openspec").rename(root / "openspec")
    registration = root / "agentic_harness/projects.yaml"
    data = yaml.safe_load(registration.read_text())
    data["projects"]["example"].update(root=".", queue="openspec/queue.yaml", code_roots=["."])
    registration.write_text(yaml.safe_dump(data))
    record["ticket"]["spec_links"] = [path.removeprefix("component/") for path in record["ticket"]["spec_links"]]
    record["scope"] = ["."]
    record["ticket"]["scope"] = ["."]
    record["authorities"][0]["scope"] = ["."]


@pytest.mark.parametrize("at_root", [False, True])
def test_no_behavior_change_intake_uses_explicit_metadata_in_selected_project(implementation, tmp_path, at_root):
    root, record = implementation
    if at_root:
        root_project(root, record)
    proposal, capability = record["ticket"]["spec_links"]
    change = (root / proposal).parent
    (root / capability).unlink()
    metadata = change / ".openspec.yaml"
    metadata.write_text("schema: spec-driven\nskip_specs: true\n")
    record["ticket"]["spec_links"] = [proposal, metadata.relative_to(root).as_posix()]
    evidence(tmp_path, record)
    normalized = intake.validate_intake(record, root)
    assert normalized["allowed_actions"] == ["implementation", "writer"]
    assert intake.validate_intake(normalized, root) == normalized


def test_root_project_behavior_change_accepts_canonical_proposal_links(implementation, tmp_path):
    root, record = implementation
    root_project(root, record)
    evidence(tmp_path, record)
    normalized = intake.validate_intake(record, root)
    assert normalized["scope"] == ["."]
    assert all(path.startswith("openspec/") for path in normalized["ticket"]["spec_links"])


@pytest.mark.parametrize("condition,diagnostic", [
    ("missing-metadata-link", "requires its skip_specs metadata link"),
    ("delta", "contradicts capability deltas"),
    ("nonboolean", "boolean skip_specs"),
    ("missing-declaration", "capability specification links"),
    ("duplicate-declaration", "duplicate configuration key"),
])
def test_no_behavior_change_intake_rejects_ambiguous_or_contradictory_declaration(implementation, tmp_path, condition, diagnostic):
    root, record = implementation
    proposal, capability = record["ticket"]["spec_links"]
    change = (root / proposal).parent
    if condition != "delta":
        (root / capability).unlink()
    metadata = change / ".openspec.yaml"
    declaration = {
        "nonboolean": 'skip_specs: "true"\n',
        "missing-declaration": 'schema: spec-driven\n',
        "duplicate-declaration": 'skip_specs: true\nskip_specs: false\n',
    }.get(condition, 'skip_specs: true\n')
    metadata.write_text(declaration)
    record["ticket"]["spec_links"] = [proposal]
    if condition != "missing-metadata-link":
        record["ticket"]["spec_links"].append(metadata.relative_to(root).as_posix())
    evidence(tmp_path, record)
    with pytest.raises(ValueError, match=diagnostic):
        intake.validate_intake(record, root)


def test_selected_project_cannot_borrow_another_projects_change_links(implementation, tmp_path):
    root, record = implementation
    record["ticket"]["spec_links"] = [path.replace("component/", "another/") for path in record["ticket"]["spec_links"]]
    for link in record["ticket"]["spec_links"]:
        path = root / link
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# A different project owns this contract\n")
    evidence(tmp_path, record)
    with pytest.raises(ValueError, match="exact owning change proposal"):
        intake.validate_intake(record, root)


def test_whole_repository_authority_does_not_expand_registered_component(implementation, tmp_path):
    root, record = implementation
    record["scope"] = record["ticket"]["scope"] = record["authorities"][0]["scope"] = ["."]
    evidence(tmp_path, record)
    with pytest.raises(ValueError, match="exceeds registered project areas"):
        intake.validate_intake(record, root)


@pytest.mark.parametrize("path", [".", "../proposal.md", "./openspec/changes/proposal.md"])
def test_root_scope_does_not_relax_file_link_validation(implementation, tmp_path, path):
    root, record = implementation
    record["ticket"]["spec_links"] = [path]
    evidence(tmp_path, record)
    with pytest.raises(ValueError, match="repository-relative paths"):
        intake.validate_intake(record, root)


@pytest.mark.parametrize("extra_path", [None, "README.md", "openspec2/notes.md", "."])
def test_root_specs_are_editable_metadata_without_expanding_domain_scope(implementation, tmp_path, extra_path):
    root, record = implementation
    root_project(root, record)
    registration = root / "agentic_harness/projects.yaml"
    data = yaml.safe_load(registration.read_text())
    data["projects"]["example"]["code_roots"] = ["apps/api"]
    registration.write_text(yaml.safe_dump(data))
    scope = ["apps/api", f"openspec/changes/{CHANGE}"]
    if extra_path is not None:
        scope.append(extra_path)
    record["scope"] = list(scope)
    record["ticket"]["scope"] = list(scope)
    record["authorities"][0]["scope"] = list(scope)
    evidence(tmp_path, record)
    if extra_path is None:
        assert intake.validate_intake(record, root)["allowed_actions"] == ["implementation", "writer"]
    else:
        with pytest.raises(ValueError, match="exceeds registered project areas"):
            intake.validate_intake(record, root)


def test_exact_approved_link_leaf_keeps_lexical_scope(tmp_path):
    import skill_links
    root = tmp_path / 'repo'; root.mkdir()
    leaf = '.agents/skills/sdw-run'
    canonical = root / skill_links.canonical_skill(leaf)
    canonical.parent.mkdir(parents=True); canonical.write_text('canonical')
    (root / leaf).parent.mkdir(parents=True)
    (root / leaf).symlink_to(skill_links.expected_target(leaf))
    record = planning()
    record['scope'] = [leaf]
    record['authorities'][0]['scope'] = [leaf]
    admitted = intake.validate_intake(record, root)
    assert admitted['scope'] == [leaf]
    assert admitted['authorities'][0]['scope'] == [leaf]
    record['scope'] = [leaf + '/SKILL.md']
    record['authorities'][0]['scope'] = record['scope']
    with pytest.raises(ValueError, match='aliased'):
        intake.validate_intake(record, root)


@pytest.mark.parametrize('relative,allowed', [
    ('agentic_harness/config/component/workflow.yaml', True),
    ('agentic_harness/config/neighbor/workflow.yaml', False),
    ('agentic_harness/tools/coordination.py', False),
    ('agentic_harness/skills/sdw-run/SKILL.md', False),
])
def test_schema_three_ticket_scope_grants_only_own_exact_settings(implementation, tmp_path, relative, allowed):
    root, record = implementation
    index_path = root / 'agentic_harness/projects.yaml'
    index = yaml.safe_load(index_path.read_text())
    original = index['projects']['example']
    settings = {key: value for key, value in original.items() if key not in {'root', 'queue'}}
    settings['code_roots'] = ['component']
    path = root / 'agentic_harness/config/component/workflow.yaml'
    path.parent.mkdir(parents=True); path.write_text(yaml.safe_dump({'schema_version': 1, **settings}))
    (root / original['queue']).rename(root / 'component/openspec/dependency-map.yaml')
    index_path.write_text(yaml.safe_dump({'schema_version': 3, 'projects': {'example': {'root': 'component'}}}))
    record['scope'] = [relative]
    record['ticket']['scope'] = [relative]
    evidence(tmp_path, record)
    if allowed:
        assert intake.validate_intake(record, root)['scope'] == [relative]
    else:
        with pytest.raises(ValueError, match='exceeds registered project areas'):
            intake.validate_intake(record, root)
