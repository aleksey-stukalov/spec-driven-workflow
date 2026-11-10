"""Offline synthetic integration/failure tests for queue and host-local coordination."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest
import yaml

MODULE = Path(__file__).resolve().parents[1] / "tools" / "coordination.py"
spec = importlib.util.spec_from_file_location("harness_coordination", MODULE)
c = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = c
spec.loader.exec_module(c)
A = "26-11-09-901-base-contract"
B = "26-11-09-902-contract-consumer"
C = "26-11-09-903-independent-docs"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def plan(root, name, ready=True):
    folder = root / "openspec" / "changes" / name
    folder.mkdir(parents=True)
    (folder / "proposal.md").write_text("# Why\nA synthetic bounded change.\n")
    if ready:
        (folder / "design.md").write_text("# Design\nTest synthetic behavior.\n")
        (folder / "tasks.md").write_text("- [ ] Verify implementation\n")
        (folder / "specs" / "synthetic").mkdir(parents=True)
        (folder / "specs" / "synthetic" / "spec.md").write_text("## ADDED Requirements\n")


def queue(root, entries):
    path = root / "openspec" / "queue.yaml"
    path.parent.mkdir(exist_ok=True)
    path.write_text(yaml.safe_dump({"queue": [{"change": name, "depends_on": deps} for name, deps in entries]}, sort_keys=False))
    return path


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Synthetic Test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "uv.lock").write_text("version = 1\n")
    (root / "source.py").write_text("value = 1\n")
    (root / ".gitignore").write_text(".venv/\nprivate/\n")
    for name in (A, B, C):
        plan(root, name)
    path = queue(root, [(A, []), (B, [A]), (C, [])])
    git(root, "add", ".")
    git(root, "commit", "-m", "synthetic baseline")
    return root, c.Project("synthetic", root, path, {"lockfiles": ["uv.lock"], "prepare": []}), git(root, "rev-parse", "HEAD")


def owned(repository, tmp_path, pid=None):
    root, project, base = repository
    store = c.CoordinationStore(root)
    path = tmp_path / "workspaces" / "task"
    claim = store.claim(project, A, "run", "session", "author", "feat/test", path, base,
                        "request:implementation", pid=pid)
    workspace = c.create_workspace(store, claim["id"], claim["generation"], "session", path,
                                   tmp_path / "workspaces", path / ".venv", "configuration:synthetic",
                                   "request:implementation")
    return store, claim, workspace, path


def reserve(store, claim, path, ident, files, mode="writer", output=None):
    return store.reserve(claim["id"], claim["generation"], "session", ident, "run", files,
                         c.source_state(path)["content_revision"], ["pytest synthetic"],
                         str(output or path.parent / f"{ident}.json"), "request:workers", mode)


def test_read_only_selection_and_full_ids(repository):
    root, project, base = repository
    store = c.CoordinationStore(root)
    assert c.select_next(project, base, store=store)["candidate"] == f"synthetic:{A}"
    assert not store.path.exists()
    assert c.validate_queue(project)[1]["depends_on"] == [A]
    assert c.select_next(project, base, explicit=B)["blockers"] == [f"dependency absent from pinned base: {A}"]
    with pytest.raises(c.CoordinationError, match="immutable"):
        c.select_next(project, "main")


def test_explicit_nonbehavioral_spec_skip_is_distinct_from_missing_contract(repository):
    root, project, base = repository
    folder = root / 'openspec/changes' / A
    (folder / 'specs/synthetic/spec.md').unlink()
    assert 'missing capability deltas' in c.planning_readiness(project, A)['blockers']
    (folder / '.openspec.yaml').write_text('schema: spec-driven\nskip_specs: true\n')
    assert c.planning_readiness(project, A)['specs_skipped'] is True
    assert c.planning_readiness(project, A)['planning_ready'] is True
    (folder / 'proposal.md').write_text('### New Capabilities\n- new-behavior: a new contract\n')
    assert 'skip_specs cannot omit a declared new capability' in c.planning_readiness(project, A)['blockers']


@pytest.mark.parametrize("data,diagnostic", [
    ({"queue": "wrong"}, "queue list"),
    ({"queue": [{"change": A}]}, "exactly change"),
    ({"queue": [{"change": "901", "depends_on": []}]}, "full change ID"),
    ({"queue": [{"change": A, "depends_on": "wrong"}]}, "must be a list"),
    ({"queue": [{"change": A, "depends_on": []}, {"change": A, "depends_on": []}]}, "duplicate full ID"),
    ({"queue": [{"change": A, "depends_on": [B]}, {"change": B, "depends_on": [A]}]}, "cyclic or out of order"),
    ({"queue": [{"change": A, "depends_on": ["26-11-09-999-missing"]}]}, "dependency"),
    ({"queue": [{"change": A, "depends_on": []}, {"change": B, "depends_on": [A, A]}]}, "duplicate dependency"),
])
def test_malformed_whole_queue(repository, data, diagnostic):
    _, project, _ = repository
    project.queue_path.write_text(yaml.safe_dump(data))
    with pytest.raises(c.CoordinationError, match=diagnostic):
        c.validate_queue(project)


def test_duplicate_yaml_keys_and_missing_active(repository):
    _, project, _ = repository
    project.queue_path.write_text("queue: []\nqueue: []\n")
    with pytest.raises(c.CoordinationError, match="duplicate queue key"):
        c.validate_queue(project)
    project.queue_path.write_text("queue: []\n")
    with pytest.raises(c.CoordinationError, match="active changes missing"):
        c.validate_queue(project)


def test_unmerged_archive_does_not_satisfy_base_then_accepted_base_does(repository):
    root, project, old_base = repository
    archive = project.changes / "archive"
    archive.mkdir()
    (project.changes / A).rename(archive / f"2026-11-09-{A}")
    selected = c.select_next(project, old_base)
    assert selected["candidate"] == f"synthetic:{C}"
    assert selected["skipped"][0]["id"] == f"synthetic:{B}"
    git(root, "add", ".")
    git(root, "commit", "-m", "accept base contract")
    accepted = git(root, "rev-parse", "HEAD")
    assert c.select_next(project, accepted)["candidate"] == f"synthetic:{B}"
    (project.changes / B / "tasks.md").write_text("- [x] all checked\n")
    result = c.select_next(project, accepted)
    assert result["ready"] and not result["implemented"] and not result["accepted"]


def test_unready_first_candidate_blocks_and_explicit_does_not_bypass(repository):
    _, project, base = repository
    (project.changes / A / "tasks.md").write_text("# No tasks\n")
    result = c.select_next(project, base)
    assert result["candidate"] == f"synthetic:{A}" and not result["ready"]
    assert "empty task list" in result["blockers"]
    assert c.select_next(project, base, explicit=C)["ready"]
    with pytest.raises(c.CoordinationError, match="not executable"):
        c.CoordinationStore(project.root).claim(project, A, "r", "s", "o", "feat/a", project.root.parent / "a", base, "auth")


def test_atomic_claim_race_across_linked_worktrees(repository, tmp_path):
    root, project, base = repository
    other = tmp_path / "linked"
    git(root, "worktree", "add", "-b", "other", str(other), base)
    projects = [project, c.Project("synthetic", other, other / "openspec" / "queue.yaml")]
    barrier = threading.Barrier(2)

    def compete(index):
        p = projects[index]
        store = c.CoordinationStore(p.root)
        barrier.wait()
        try:
            return store.claim(p, A, "run", f"session-{index}", f"owner-{index}", f"feat/{index}",
                               tmp_path / f"workspace-{index}", base, "auth")
        except c.CoordinationError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, range(2)))
    assert sum(isinstance(r, dict) for r in results) == 1
    loser = next(r for r in results if isinstance(r, str))
    assert "existing claim" in loser and "owner-" in loser
    store = c.CoordinationStore(other)
    selected = c.select_next(project, base, store=store)
    assert selected["candidate"] == f"synthetic:{A}" and not selected["ready"]
    claim = store.get_claim(f"synthetic:{A}")
    with pytest.raises(c.CoordinationError, match="compare-and-set"):
        store.transition(claim["id"], 999, claim["session"], "running", "auth")
    changed = store.transition(claim["id"], claim["generation"], claim["session"], "blocked", "auth", {"unresolved": "original result missing"})
    assert changed["generation"] == claim["generation"] + 1
    assert changed["recovery"]["unresolved"]


def test_workspace_preserves_dirty_shared_checkout_and_rejects_alias(repository, tmp_path):
    root, _, _ = repository
    (root / "source.py").write_text("unrelated dirty bytes\n")
    (root / "private-note").write_text("untracked unrelated\n")
    store, claim, workspace, path = owned(repository, tmp_path)
    assert (root / "source.py").read_text() == "unrelated dirty bytes\n"
    assert (root / "private-note").exists()
    assert (path / "source.py").read_text() == "value = 1\n"
    assert workspace["base_revision"] == claim["base_revision"]
    assert workspace["environment"] == str(path / ".venv")
    alias = tmp_path / "alias"
    alias.symlink_to(path.parent, target_is_directory=True)
    with pytest.raises(c.CoordinationError, match="alias"):
        c.canonical_location(alias / "task", path.parent)
    with pytest.raises(c.CoordinationError, match="outside"):
        c.canonical_location(tmp_path / "outside", path.parent)
    with pytest.raises(c.CoordinationError, match="already owned"):
        c.adopt_workspace(store, claim["id"], 1, "session", path, path.parent,
                          path / ".venv", "config", "auth")


def test_assignments_overlap_capacity_outputs_and_sibling_release(repository, tmp_path):
    store, claim, _, path = owned(repository, tmp_path)
    first = reserve(store, claim, path, "first", ["source.py"])
    with pytest.raises(c.CoordinationError, match="overlapping"):
        reserve(store, claim, path, "overlap", ["source.py"])
    with pytest.raises(c.CoordinationError, match="output already"):
        reserve(store, claim, path, "same-output", ["uv.lock"], output=first["output"])
    reserve(store, claim, path, "second", ["uv.lock"])
    with pytest.raises(c.CoordinationError, match="two-worker"):
        reserve(store, claim, path, "third", ["new.py"])
    store.settle("first", "original:first.json", "auth")
    with pytest.raises(c.CoordinationError, match="siblings"):
        store.release_assignments("run", "auth")
    with pytest.raises(c.CoordinationError, match="settle and release"):
        store.transition(claim["id"], 1, "session", "completed", "auth")
    store.settle("second", "original:second.json", "auth")
    assert len(store.release_assignments("run", "auth")) == 2
    assert store.transition(claim["id"], 1, "session", "completed", "auth")["state"] == "completed"


def test_freeze_reviewers_and_changed_source_invalidate(repository, tmp_path):
    store, claim, _, path = owned(repository, tmp_path)
    rev = c.source_state(path)["content_revision"]
    store.freeze(path, rev, "auth")
    with pytest.raises(c.CoordinationError, match="frozen"):
        reserve(store, claim, path, "fixer", ["source.py"])
    reserve(store, claim, path, "reviewer", ["source.py"], mode="reviewer")
    with pytest.raises(c.CoordinationError, match="not settled"):
        store.thaw(path, "auth")
    (path / "source.py").write_text("changed during review\n")
    store.settle("reviewer", "original:review.json", "auth")
    store.release_assignments("run", "auth")
    assert not store.thaw(path, "auth")["valid"]


def reconciliation():
    return dict(original_results="evidence:originals", budget_ledger="ledger:retained",
                decisions="decisions:retained", operation_receipts="receipts:retained")


def test_dirty_recovery_and_resume_preserve_bytes_and_ledger(repository, tmp_path):
    store, claim, _, path = owned(repository, tmp_path, pid=99999999)
    (path / "source.py").write_text("interrupted writer bytes\n")
    (path / "new.py").write_text("intended untracked\n")
    with pytest.raises(c.CoordinationError, match="reconciliation"):
        c.resume_workspace(store, claim["id"], 1, "session", "auth")
    state = c.source_state(path)
    resumed = c.resume_workspace(store, claim["id"], 1, "session", "auth", state, reconciliation())
    assert resumed["recovery"]["budget_ledger"] == "ledger:retained"
    recovered = c.recover_claim(store, claim["id"], 1, "session", "new-session", "new-owner", "auth", state, reconciliation())
    assert recovered["run"] == "run" and recovered["state"] == "blocked"
    assert recovered["generation"] == 2
    assert (path / "new.py").read_text() == "intended untracked\n"
    with pytest.raises(c.CoordinationError, match="compare-and-set"):
        store.transition(claim["id"], 1, "session", "running", "auth")


def test_expired_live_claim_and_unknown_liveness_do_not_transfer(repository, tmp_path):
    store, claim, _, path = owned(repository, tmp_path)
    with store.transaction() as db:
        current = store._get(db, "claim", claim["id"])
        current["lease_expires_at"] = 0
        store._put(db, "claim", claim["id"], current)
    with pytest.raises(c.CoordinationError, match="live or liveness unknown"):
        c.recover_claim(store, claim["id"], 1, "session", "next", "next", "auth", c.source_state(path), reconciliation())
    assert c._alive(None, "unknown") is None


def test_cleanup_rechecks_new_protections_and_retains_branch(repository, tmp_path):
    store, claim, _, path = owned(repository, tmp_path)
    store.transition(claim["id"], 1, "session", "completed", "auth")
    recoverability = cleanup_retention(store, claim, path, tmp_path)
    before = store.path.stat().st_mtime_ns
    inventory = c.cleanup_inventory(store, [str(path)], recoverability)
    assert store.path.stat().st_mtime_ns == before
    assert inventory["items"][0]["eligible"]
    pin = store.pin(path / ".venv", "import", "import:still-running", "auth")
    refused = c.apply_cleanup(store, inventory, "user:approve-exact-path")
    assert not refused[0]["removed"] and "import pin" in refused[0]["reasons"][0]
    assert path.exists()
    store.unpin(pin["id"], "import:stopped")
    (path / "untracked").write_text("preserve\n")
    assert not c.apply_cleanup(store, inventory, "auth")[0]["removed"]
    (path / "untracked").unlink()
    fresh = c.cleanup_inventory(store, [str(path)], recoverability)
    result = c.apply_cleanup(store, fresh, "user:approve-exact-path")
    assert result[0]["removed"] and not path.exists()
    assert git(store.repository, "rev-parse", "refs/heads/feat/test") == claim["base_revision"]


def cleanup_retention(store, claim, path, tmp_path, originals=None):
    sys.path.insert(0, str(MODULE.parent))
    import evidence
    bundle = tmp_path / 'retained-cleanup'
    evidence.materialize(path, bundle, ['source.py', 'uv.lock'], project=claim['project'],
                         change=claim['change'], run_id=claim['run'], base=claim['base_revision'], policy='plans-v1')
    return {str(path): {'bundle': str(bundle), 'originals': originals or []}}


def cleanup_pair(repository, tmp_path, evidence_location):
    root, project, base = repository
    store, first, _, first_path = owned(repository, tmp_path)
    second_path = tmp_path / "workspaces" / "second"
    second = store.claim(project, C, "run2", "session2", "author2", "feat/second",
                         second_path, base, "auth")
    c.create_workspace(store, second['id'], second['generation'], 'session2', second_path,
                       second_path.parent, second_path / '.venv', 'config:second', 'auth')
    original = (second_path / '.venv' if evidence_location == 'original' else tmp_path) / 'first-original.json'
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_text('{"complete":true,"original":"retain these exact bytes"}')
    reserve(store, first, first_path, 'first-author', ['source.py'], output=original)
    store.settle('first-author', str(original), 'auth')
    store.release_assignments(first['run'], 'auth')
    store.transition(first['id'], first['generation'], first['session'], 'completed', 'auth')
    store.transition(second['id'], second['generation'], second['session'], 'completed', 'auth')
    first_destination = second_path / '.venv' if evidence_location == 'bundle' else tmp_path / 'first-retention'
    originals = [{'path': str(original), 'sha256': hashlib.sha256(original.read_bytes()).hexdigest()}]
    retention = cleanup_retention(store, first, first_path, first_destination, originals)
    retention.update(cleanup_retention(store, second, second_path, tmp_path / 'second-retention'))
    assert git(first_path, 'status', '--porcelain') == git(second_path, 'status', '--porcelain') == ''
    return store, first_path, second_path, original, retention


@pytest.mark.parametrize('evidence_location', ['original', 'bundle'])
def test_cleanup_batch_preserves_evidence_hosted_by_another_worktree(repository, tmp_path, evidence_location):
    store, first, second, original, retention = cleanup_pair(repository, tmp_path, evidence_location)
    original_bytes = original.read_bytes()
    bundle_manifest = Path(retention[str(first)]['bundle']) / 'manifest.json'
    manifest_bytes = bundle_manifest.read_bytes()
    inventory = c.cleanup_inventory(store, [str(first), str(second)], retention)
    assert not any(item['eligible'] for item in inventory['items'])
    assert any('outside every linked worktree' in reason for reason in inventory['items'][0]['reasons'])
    assert any('retained evidence dependency' in reason for reason in inventory['items'][1]['reasons'])
    result = c.apply_cleanup(store, inventory, 'user:reviewed-batch-cleanup')
    assert not any(item['removed'] for item in result)
    assert first.is_dir() and second.is_dir()
    assert (first / 'source.py').read_bytes() == (second / 'source.py').read_bytes() == b'value = 1\n'
    assert original.read_bytes() == original_bytes
    assert bundle_manifest.read_bytes() == manifest_bytes
    # A containing worktree remains protected if a later request omits the
    # original owner from the cleanup batch. Assignment originals are durable
    # dependencies; supplied bundle references protect their host too.
    references = {str(second): retention[str(second)]} if evidence_location == 'original' else retention
    later = c.cleanup_inventory(store, [str(second)], references)
    assert not later['items'][0]['eligible']
    assert not c.apply_cleanup(store, later, 'user:reviewed-single-cleanup')[0]['removed']
    assert original.read_bytes() == original_bytes and bundle_manifest.read_bytes() == manifest_bytes


def test_cleanup_recheck_preserves_new_cross_worktree_evidence_dependency(repository, tmp_path):
    store, first, second, original, retention = cleanup_pair(repository, tmp_path, 'external')
    inventory = c.cleanup_inventory(store, [str(first), str(second)], retention)
    assert all(item['eligible'] for item in inventory['items'])
    original_bytes = original.read_bytes()
    relocated = second / '.venv' / original.name
    relocated.parent.mkdir()
    original.rename(relocated)
    original.symlink_to(relocated)
    # An ignored path keeps the host worktree clean; the evidence dependency
    # itself, rather than Git's ordinary dirtiness check, must prevent removal.
    assert git(second, 'status', '--porcelain') == ''
    result = c.apply_cleanup(store, inventory, 'user:reviewed-before-evidence-move')
    assert not any(item['removed'] for item in result)
    assert first.is_dir() and second.is_dir()
    assert original.read_bytes() == relocated.read_bytes() == original_bytes


def test_prior_cleanup_recoverability_protects_its_bundle_host(repository, tmp_path):
    store, first, second, original, retention = cleanup_pair(repository, tmp_path, 'bundle')
    bundle = Path(retention[str(first)]['bundle'])
    manifest_bytes = (bundle / 'manifest.json').read_bytes()
    # Model an existing persisted cleanup record from the earlier runtime.
    # The source checkout is gone, while its required retained bundle remains.
    git(store.repository, 'worktree', 'remove', str(first))
    with store.transaction() as db:
        workspace = store._get(db, 'workspace', str(first))
        workspace.update(state='removed', recoverability=retention[str(first)])
        store._put(db, 'workspace', str(first), workspace)
    inventory = c.cleanup_inventory(store, [str(second)], {str(second): retention[str(second)]})
    assert not inventory['items'][0]['eligible']
    assert not c.apply_cleanup(store, inventory, 'user:reviewed-second-cleanup')[0]['removed']
    assert second.is_dir() and original.is_file()
    assert (bundle / 'manifest.json').read_bytes() == manifest_bytes


def test_cleanup_batch_can_remove_its_callers_checkout_without_losing_records(repository, tmp_path):
    _, first, second, original, retention = cleanup_pair(repository, tmp_path, 'external')
    original_bytes = original.read_bytes()
    store = c.CoordinationStore(first)
    inventory = c.cleanup_inventory(store, [str(first), str(second)], retention)
    assert all(item['eligible'] for item in inventory['items'])
    result = c.apply_cleanup(store, inventory, 'user:reviewed-both-worktrees')
    assert all(item['removed'] for item in result)
    assert not first.exists() and not second.exists()
    assert all(record['state'] == 'removed' for record in store.records('workspace'))
    assert original.read_bytes() == original_bytes
    assert all((Path(reference['bundle']) / 'manifest.json').is_file() for reference in retention.values())


def test_cleanup_rechecks_retained_source_and_original_results(repository, tmp_path):
    store, claim, _, path = owned(repository, tmp_path)
    original = tmp_path / 'original.json'
    original.write_text('{"status":"success"}')
    reserve(store, claim, path, 'author', ['source.py'], output=original)
    store.settle('author', str(original), 'auth')
    store.release_assignments('run', 'auth')
    store.transition(claim['id'], 1, 'session', 'completed', 'auth')
    retention = cleanup_retention(store, claim, path, tmp_path)
    missing = c.cleanup_inventory(store, [str(path)], retention)
    assert 'original assignment results are not all retained' in missing['items'][0]['reasons']
    retention[str(path)]['originals'] = [{'path': str(original), 'sha256': hashlib.sha256(original.read_bytes()).hexdigest()}]
    good = c.cleanup_inventory(store, [str(path)], retention)
    assert good['items'][0]['eligible']
    original.write_text('tampered')
    assert not c.apply_cleanup(store, good, 'auth')[0]['removed']
    assert path.exists()
    original.write_text('{"status":"success"}')
    retained_source = Path(retention[str(path)]['bundle']) / 'source/source.py'
    retained_source.chmod(0o644)
    retained_source.write_text('tampered')
    assert not c.apply_cleanup(store, good, 'auth')[0]['removed']
    assert path.exists()


def test_cleanup_dirty_unreconciled_missing_retention_and_evidence_pin(repository, tmp_path):
    store, claim, _, path = owned(repository, tmp_path)
    store.pin(path, "evidence", "source:review-bundle-needed", "auth")
    (path / "source.py").write_text("dirty\n")
    inventory = c.cleanup_inventory(store, [str(path)], {})
    reasons = inventory["items"][0]["reasons"]
    assert any("dirty" in r for r in reasons)
    assert any("claim" in r for r in reasons)
    assert any("evidence pin" in r for r in reasons)
    assert any("recoverability" in r for r in reasons)
    with pytest.raises(c.CoordinationError, match="authorization"):
        c.apply_cleanup(store, inventory, "")


def test_cli_json_success_and_failure_read_only(repository, tmp_path):
    root, project, base = repository
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"project": {"project_id": project.project_id, "root": str(root),
                                              "queue_path": str(project.queue_path)}, "base_revision": base}))
    result = subprocess.run([sys.executable, str(MODULE), "next", "--repository", str(root),
                             "--request", str(request)], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["result"]["candidate"] == f"synthetic:{A}"
    assert not c.CoordinationStore(root).path.exists()
    request.write_text('{"authorization":""}')
    result = subprocess.run([sys.executable, str(MODULE), "pin", "--repository", str(root),
                             "--request", str(request)], capture_output=True, text=True)
    assert result.returncode == 1 and not json.loads(result.stdout)["ok"]


def test_source_revision_includes_index_head_and_untracked_but_not_ignored(repository):
    root, _, _ = repository
    original = c.source_state(root)
    (root / "source.py").write_text("staged bytes\n")
    git(root, "add", "source.py")
    (root / "source.py").write_text("value = 1\n")
    staged = c.source_state(root)
    assert staged["content_revision"] != original["content_revision"]
    git(root, "restore", "--staged", "source.py")
    assert c.source_state(root) == original
    (root / "private").mkdir()
    (root / "private" / "secret").write_text("ignored bytes")
    assert c.source_state(root) == original
    (root / " leading-name.py").write_text("intended new test\n")
    assert c.source_state(root)["content_revision"] != original["content_revision"]


def test_workspace_preflight_and_interrupted_create_intent(repository, tmp_path, monkeypatch):
    root, project, base = repository
    store = c.CoordinationStore(root)
    path = tmp_path / "workspaces" / "interrupted"
    claim = store.claim(project, A, "run", "session", "author", "feat/interrupted", path, base, "auth")
    original_put = store._put

    def fail_final_record(db, kind, key, data):
        if kind == "workspace":
            raise RuntimeError("synthetic process failure after git succeeds")
        return original_put(db, kind, key, data)

    monkeypatch.setattr(store, "_put", fail_final_record)
    with pytest.raises(RuntimeError, match="process failure"):
        c.create_workspace(store, claim["id"], 1, "session", path, path.parent,
                           path / ".venv", "config", "auth")
    assert path.is_dir()
    assert store.records("workspace-intent")[0]["state"] == "attempted"
    assert not store.records("workspace")
    monkeypatch.setattr(store, "_put", original_put)
    adopted = c.adopt_workspace(store, claim["id"], 1, "session", path, path.parent,
                                path / ".venv", "config", "auth:reconcile-existing-operation")
    assert adopted["expected_source"]["head"] == base


def test_claim_requires_scope_and_project_repository_identity(repository, tmp_path):
    root, project, base = repository
    store = c.CoordinationStore(root)
    with pytest.raises(c.CoordinationError, match="authorization"):
        store.claim(project, A, "run", "session", "owner", "feat/test", tmp_path / "task", base, "")
    other = tmp_path / "other-repo"
    other.mkdir()
    git(other, "init", "-b", "main")
    other_store = c.CoordinationStore(other)
    with pytest.raises(c.CoordinationError, match="another repository"):
        other_store.claim(project, A, "run", "session", "owner", "feat/test", tmp_path / "task", base, "auth")
    with pytest.raises(c.CoordinationError, match="root/queue"):
        c.Project("missing", root / "absent", root / "absent" / "queue.yaml")


def test_resume_changed_branch_lock_and_external_import_block(repository, tmp_path):
    store, claim, _, path = owned(repository, tmp_path)
    pin = store.pin(path / ".venv", "import", "import:live", "auth")
    with pytest.raises(c.CoordinationError, match="import/environment"):
        c.resume_workspace(store, claim["id"], 1, "session", "auth")
    store.unpin(pin["id"], "auth:import-stopped")
    (path / "uv.lock").write_text("changed dependency lock\n")
    with pytest.raises(c.CoordinationError, match="lock changed"):
        c.resume_workspace(store, claim["id"], 1, "session", "auth")
    (path / "uv.lock").write_text("version = 1\n")
    git(path, "checkout", "-b", "unexpected")
    with pytest.raises(c.CoordinationError, match="branch changed"):
        c.resume_workspace(store, claim["id"], 1, "session", "auth")


def test_aggregate_reservations_across_changes_and_phases(repository, tmp_path):
    root, project, base = repository
    store, first, _, first_path = owned(repository, tmp_path)
    second_path = tmp_path / "workspaces" / "second"
    second = store.claim(project, C, "run", "session", "author", "feat/second", second_path, base, "auth")
    c.create_workspace(store, second["id"], second["generation"], "session", second_path,
                       second_path.parent, second_path / ".venv", "config:second", "auth")
    reserve(store, first, first_path, "design-author", ["source.py"])
    reserve(store, second, second_path, "code-author", ["source.py"])
    with pytest.raises(c.CoordinationError, match="two-worker"):
        reserve(store, second, second_path, "extra-scout", ["uv.lock"])
    store.settle("design-author", "original:design.json", "auth")
    with pytest.raises(c.CoordinationError, match="siblings"):
        store.release_assignments("run", "auth")


def test_preflight_checked_out_branch_and_declared_missing_lock(repository, tmp_path):
    root, project, base = repository
    store = c.CoordinationStore(root)
    path = tmp_path / "workspaces" / "blocked"
    claim = store.claim(project, A, "run", "session", "owner", "main", path, base, "auth")
    with pytest.raises(c.CoordinationError, match="already exists"):
        c.create_workspace(store, claim["id"], 1, "session", path, path.parent,
                           path / ".venv", "config", "auth")
    assert not path.exists()
    assert git(root, "symbolic-ref", "--short", "HEAD") == "main"
    assert git(root, "status", "--porcelain") == ""
    store.transition(claim["id"], 1, "session", "released", "auth")
    (root / "uv.lock").unlink()
    git(root, "add", "uv.lock")
    git(root, "commit", "-m", "synthetic no dependency lock")
    no_lock_base = git(root, "rev-parse", "HEAD")
    claim = store.claim(project, A, "run", "session", "owner", "feat/no-lock", path, no_lock_base, "auth")
    workspace = c.create_workspace(store, claim["id"], claim["generation"], "session", path, path.parent,
                                   path / ".venv", "config", "auth")
    assert workspace["lockfiles"] == {"uv.lock": None}
    assert git(root, "symbolic-ref", "--short", "HEAD") == "main"
    assert git(root, "status", "--porcelain") == ""
    (path / "uv.lock").write_text("new declared dependency lock\n")
    with pytest.raises(c.CoordinationError, match="lock changed"):
        c._inspect_workspace(store, workspace)


def test_workspace_cannot_nest_in_shared_checkout(repository):
    root, project, base = repository
    store = c.CoordinationStore(root)
    path = root / "workspaces" / "nested"
    claim = store.claim(project, A, "run", "session", "owner", "feat/nested", path, base, "auth")
    with pytest.raises(c.CoordinationError, match="overlaps an existing worktree"):
        c.create_workspace(store, claim["id"], 1, "session", path, path.parent,
                           path / ".venv", "config", "auth")
    assert not path.exists()
    assert git(root, "status", "--porcelain") == ""


def test_non_python_project_has_no_implicit_lock_or_prepare_requirement(repository, tmp_path):
    root, original_project, _ = repository
    (root / "uv.lock").unlink()
    (root / "source.py").unlink()
    (root / "index.js").write_text("export const value = 1;\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "non-Python project with no dependency manager")
    project = c.Project("synthetic", root, original_project.queue_path)
    assert project.environment == {"lockfiles": [], "prepare": []}
    store, claim, workspace, path = owned((root, project, git(root, "rev-parse", "HEAD")), tmp_path)
    assert claim["environment_policy"] == project.environment
    assert workspace["lockfiles"] == {}
    assert not (path / "uv.lock").exists()
    assert not (path / ".venv").exists()
    assert c._inspect_workspace(store, workspace) == workspace["expected_source"]


def test_declared_multiple_lockfiles_are_repo_relative_even_for_nested_project(repository, tmp_path):
    root, original_project, _ = repository
    (root / "module").mkdir()
    (root / "module/package-lock.json").write_text('{"lockfileVersion": 3}\n')
    original_project.queue_path.parent.rename(root / "module/openspec")
    git(root, "add", ".")
    git(root, "commit", "-m", "nested project with two declared dependency locks")
    commands = [["npm", "ci", "--prefix", "module"]]
    project = c.Project("synthetic", root / "module", root / "module/openspec/queue.yaml",
                        {"lockfiles": ["uv.lock", "module/package-lock.json"], "prepare": commands})
    store, claim, workspace, path = owned((root, project, git(root, "rev-parse", "HEAD")), tmp_path)
    assert set(workspace["lockfiles"]) == {"uv.lock", "module/package-lock.json"}
    assert claim["environment_policy"]["prepare"] == commands
    # Preparation is an attested caller action, never an implicit subprocess.
    assert not (path / "module/node_modules").exists()
    (path / "module/package-lock.json").unlink()
    with pytest.raises(c.CoordinationError, match="lock changed"):
        c._inspect_workspace(store, workspace)


@pytest.mark.parametrize("kind", ["file-link", "parent-link", "directory"])
def test_declared_lock_aliases_and_directories_rejected_before_worktree_creation(repository, tmp_path, kind):
    root, project, _ = repository
    (root / "uv.lock").unlink()
    if kind == "file-link":
        (root / "uv.lock").symlink_to("source.py")
        relative = "uv.lock"
    elif kind == "parent-link":
        (root / "alias").symlink_to("openspec", target_is_directory=True)
        relative = "alias/queue.yaml"
    else:
        (root / "uv.lock").mkdir()
        (root / "uv.lock/entry").write_text("not a lockfile")
        relative = "uv.lock"
    git(root, "add", ".")
    git(root, "commit", "-m", "invalid dependency lock location")
    project = c.Project("synthetic", root, project.queue_path,
                        {"lockfiles": [relative], "prepare": []})
    store = c.CoordinationStore(root)
    path = tmp_path / "workspaces" / "blocked-lock"
    claim = store.claim(project, A, "run", "session", "owner", "feat/invalid-lock", path,
                        git(root, "rev-parse", "HEAD"), "auth")
    with pytest.raises(c.CoordinationError, match="not a regular file in base"):
        c.create_workspace(store, claim["id"], claim["generation"], "session", path,
                           path.parent, path / ".environment", "config", "auth")
    assert not path.exists()
    assert git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("relative", [".", "../outside", "nested/../lock", "/outside", ".git/config", "nested//lock", "nested\\lock"])
def test_project_environment_rejects_noncanonical_locks(repository, relative):
    root, project, _ = repository
    with pytest.raises(c.CoordinationError, match="repository-relative"):
        c.Project("synthetic", root, project.queue_path, {"lockfiles": [relative]})


def test_registered_project_cli_retains_environment_policy(repository, tmp_path):
    root, project, base = repository
    registration = {"id": "synthetic", "root": ".", "queue": "openspec/queue.yaml",
                    "code_roots": ["."], "checks": [["node", "--version"]],
                    "environment": {"lockfiles": ["uv.lock"], "prepare": []}}
    payload = dict(project=registration, change=A, run="run", session="session", owner="owner",
                   branch="feat/registered", worktree=str(tmp_path / "workspaces/registered"),
                   base_revision=base, authorization="request:explicit-claim")
    request = tmp_path / "claim-request.json"
    request.write_text(json.dumps(payload))
    assert c.main(["claim", "--repository", str(root), "--request", str(request)]) == 0
    claim = c.CoordinationStore(root).get_claim(f"synthetic:{A}")
    assert claim["environment_policy"] == registration["environment"]
    assert not Path(payload["worktree"]).exists()
    assert git(root, "status", "--porcelain") == ""


@pytest.mark.parametrize("registration", ["missing", None, {"id": "synthetic", "root": "."}])
def test_invalid_cli_project_resolution_returns_blocker(repository, tmp_path, capsys, registration):
    root, _, _ = repository
    # A missing or ambiguous registry must not escape the CLI error contract.
    registry = root / "agentic_harness/projects.yaml"
    registry.parent.mkdir()
    entry = {"root": "first", "queue": "first/openspec/queue.yaml", "code_roots": ["first"], "checks": [["true"]]}
    for folder in ("first", "module"):
        nested = root / folder / "openspec"
        nested.mkdir(parents=True)
        (nested / "config.yaml").write_text("schema: spec-driven\n")
        (nested / "queue.yaml").write_text("queue: []\n")
    registry.write_text(yaml.safe_dump({"schema_version": 1, "projects": {
        "one": entry,
        "two": {"root": "module", "queue": "module/openspec/queue.yaml", "code_roots": ["module"], "checks": [["true"]]},
    }}))
    request = tmp_path / "bad-project.json"
    request.write_text(json.dumps({"project": registration}))
    sys.path.insert(0, str(MODULE.parent))
    try:
        assert c.main(["list", "--repository", str(root), "--request", str(request)]) == 1
    finally:
        sys.path.remove(str(MODULE.parent))
    response = json.loads(capsys.readouterr().out)
    assert response["ok"] is False and response["blocker"]
    expected = "multiple registered projects" if registration is None else "unknown OpenSpec project" if isinstance(registration, str) else "queue"
    assert expected in response["blocker"]


def test_link_assignment_retains_leaf_and_conflicts_with_legacy_child(repository, tmp_path):
    import skill_links
    store, claim, workspace, path = owned(repository, tmp_path)
    leaf = '.agents/skills/sdw-run'
    child = leaf + '/SKILL.md'
    old = path / child; old.parent.mkdir(parents=True); old.write_text('copied body')
    assignment = reserve(store, claim, path, 'old-child', [child])
    assert assignment['files'] == [str(old)]
    old.unlink(); old.parent.rmdir()
    canonical = path / skill_links.canonical_skill(leaf)
    canonical.parent.mkdir(parents=True); canonical.write_text('canonical body')
    (path / leaf).symlink_to(skill_links.expected_target(leaf))
    with pytest.raises(c.CoordinationError, match='overlapping writer'):
        reserve(store, claim, path, 'new-leaf', [leaf])
    with pytest.raises(c.CoordinationError, match='aliased'):
        reserve(store, claim, path, 'linked-child', [child])
    store.settle('old-child', 'synthetic original result', 'synthetic complete')
    store.release_assignments('run', 'synthetic complete')
    assignment = reserve(store, claim, path, 'leaf-after-release', [leaf])
    assert assignment['files'] == [str(path / leaf)]
    assert str(canonical) not in assignment['files']


@pytest.mark.parametrize('document', ['queue: [\n', 'queue: &entries []\n', 'queue: [{change: first, depends_on: [[invalid]]}]\n'])
def test_shared_dependency_parser_reports_coordination_authority(repository, document):
    _, project, _ = repository
    project.queue_path.write_text(document)
    with pytest.raises(c.CoordinationError) as error:
        c.validate_queue(project)
    assert str(project.queue_path) in str(error.value)
