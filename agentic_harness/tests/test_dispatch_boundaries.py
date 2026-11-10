"""Regression tests for SAFETY-R1 dispatch ownership, role and prompt boundaries."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from test_runtime_integration import (
    repository, setup_dispatch, reference, git, coordination, dispatch, evidence, plan_runtime, CHANGE,
)


def writer_setup(repository, tmp_path, role='design_author', owned=None):
    request, ledger, store, manifest = setup_dispatch(repository, tmp_path)
    root = Path(request['worktree'])
    store.thaw(root, 'synthetic author assignment')
    owned = owned or [f'project/openspec/changes/{CHANGE}/design.md']
    record = json.loads(Path(request['intake']['path']).read_text())
    record.update(mode='planning', scope=owned)
    record['authorities'][0].update(scope=owned, actions=['planning', 'escalate'])
    request['intake'] = reference(Path(request['intake']['path']), record)
    route = plan_runtime.routes()['steps'][role]['routes']['codex']
    worker = request['admission']['reviewers'][0]
    worker.update(step=role, owned_paths=owned,
        attestation=dict(source='synthetic client support', supported_models=[route['model']],
            supported_efforts={route['model']: [route['effort']]}, effective_model=route['model'], effective_effort=route['effort']))
    request.update(kind='single', admission=worker, prompts=request['prompts'][:1])
    return request, ledger, store, manifest


def forbidden(*args, **kwargs):
    pytest.fail('provider must never start on a blocked boundary')


def assert_not_started(request, ledger, store):
    assert not Path(request['evidence_dir']).exists()
    state = ledger.status('run')
    assert state['attempts'] == {} and state['launches'] == {} and state['rounds'] == []
    assert not store.records('assignment')


def test_identical_source_in_shared_checkout_cannot_rebind_writer_cwd(repository, tmp_path):
    request, ledger, store, _ = writer_setup(repository, tmp_path)
    owned = Path(request['worktree'])
    (repository / 'untracked.py').write_bytes((owned / 'untracked.py').read_bytes())
    assert coordination.source_state(repository)['content_revision'] == coordination.source_state(owned)['content_revision']
    before = (repository / request['admission']['owned_paths'][0]).read_bytes()
    request['worktree'] = str(repository)
    with pytest.raises(ValueError, match='exact owned claim'):
        dispatch.execute(request, run=forbidden)
    assert (repository / request['admission']['owned_paths'][0]).read_bytes() == before
    assert_not_started(request, ledger, store)


def test_identical_source_in_other_linked_worktree_cannot_borrow_claim(repository, tmp_path):
    request, ledger, store, manifest = writer_setup(repository, tmp_path)
    other = tmp_path / 'other-linked-tree'
    git(repository, 'worktree', 'add', '-b', 'feat/other-linked', str(other), manifest['base_commit'])
    (other / 'untracked.py').write_bytes((Path(request['worktree']) / 'untracked.py').read_bytes())
    assert coordination.source_state(other)['content_revision'] == coordination.source_state(Path(request['worktree']))['content_revision']
    request['worktree'] = str(other)
    with pytest.raises(ValueError, match='exact owned claim'):
        dispatch.execute(request, run=forbidden)
    assert_not_started(request, ledger, store)


@pytest.mark.parametrize('field,value', [('run', 'another-run'), ('branch', 'feat/wrong-record'), ('owner', 'other-owner')])
def test_workspace_record_scope_and_branch_must_match_claim(repository, tmp_path, field, value):
    request, ledger, store, _ = writer_setup(repository, tmp_path)
    with store.transaction() as db:
        path = request['worktree']
        workspace = store._get(db, 'workspace', path)
        workspace[field] = value
        store._put(db, 'workspace', path, workspace)
    with pytest.raises(ValueError, match='workspace/claim'):
        dispatch.execute(request, run=forbidden)
    assert_not_started(request, ledger, store)


def test_live_branch_and_recorded_base_are_revalidated_before_output(repository, tmp_path):
    request, ledger, store, _ = writer_setup(repository, tmp_path)
    git(Path(request['worktree']), 'checkout', '-b', 'feat/unrecorded')
    with pytest.raises(ValueError, match='workspace branch changed'):
        dispatch.execute(request, run=forbidden)
    assert_not_started(request, ledger, store)


def test_registry_environment_declaration_cannot_replace_pinned_claim_policy(repository, tmp_path):
    request, ledger, store, _ = writer_setup(repository, tmp_path)
    path = Path(request['worktree']) / 'agentic_harness/projects.yaml'
    config = yaml.safe_load(path.read_text())
    config['projects']['synthetic']['environment'] = {'lockfiles': [], 'prepare': []}
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match='environment policy changed'):
        dispatch.execute(request, run=forbidden)
    assert_not_started(request, ledger, store)


def test_planning_home_is_separate_from_application_code_roots(repository, tmp_path):
    path = repository / 'agentic_harness/projects.yaml'
    config = yaml.safe_load(path.read_text())
    config['projects']['synthetic']['code_roots'] = ['application']
    path.write_text(yaml.safe_dump(config))
    git(repository, 'add', '.'); git(repository, 'commit', '-m', 'separate synthetic code scope')
    request, ledger, store, manifest = writer_setup(repository, tmp_path)
    def fake(argv, **kwargs):
        result = dict(complete=True, coverage_complete=True, truncated=False, findings=[], input_revision=manifest['input_revision'])
        Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(result))
        return SimpleNamespace(returncode=0, stdout='{}\n', stderr='')
    assert dispatch.execute(request, run=fake)['status'] == 'settled'
    assert ledger.status('run')['attempts']['design_author'] == 1


@pytest.mark.parametrize('role', ['design_author', 'design_fixer', 'lead_plan', 'lead_verify', 'escalation'])
def test_planning_authority_never_allows_application_code_writers(repository, tmp_path, role):
    request, ledger, store, _ = writer_setup(repository, tmp_path, role, ['project/application.py'])
    with pytest.raises(ValueError, match='selected active change|verified implementation intake'):
        dispatch.execute(request, run=forbidden)
    assert not (Path(request['worktree']) / 'project/application.py').exists()
    assert_not_started(request, ledger, store)


@pytest.mark.parametrize('path', [
    f'project/openspec/changes/{CHANGE}/injected.py',
    'project/openspec/config.yaml',
    f'project/openspec/changes/26-11-09-999-another-change/design.md',
    f'project/openspec/changes/archive/2026-11-09-{CHANGE}/proposal.md',
])
def test_design_writer_is_limited_to_selected_active_markdown_and_metadata(repository, tmp_path, path):
    request, ledger, store, _ = writer_setup(repository, tmp_path, owned=[path])
    with pytest.raises(ValueError, match='selected active change'):
        dispatch.execute(request, run=forbidden)
    assert_not_started(request, ledger, store)


@pytest.mark.parametrize('role,filename', [('design_author', 'design.md'), ('design_author', '.openspec.yaml'), ('lead_plan', 'proposal.md')])
def test_planning_artifact_writes_are_admitted_with_explicit_native_constraints(repository, tmp_path, role, filename):
    relative = f'project/openspec/changes/{CHANGE}/{filename}'
    request, ledger, store, manifest = writer_setup(repository, tmp_path, role, [relative])
    calls = []
    def fake(argv, **kwargs):
        calls.append(kwargs)
        assert Path(kwargs['cwd']) == Path(request['worktree'])
        assert 'Assignment boundaries (mandatory)' in kwargs['input']
        assert json.dumps([relative]) in kwargs['input']
        assert 'Write only the exact owned paths' in kwargs['input']
        (Path(kwargs['cwd']) / relative).write_text('Synthetic authorized planning artifact.\n')
        result = dict(complete=True, coverage_complete=True, truncated=False, findings=[], input_revision=manifest['input_revision'])
        Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(result))
        return SimpleNamespace(returncode=0, stdout='{}\n', stderr='')
    assert dispatch.execute(request, run=fake)['status'] == 'settled'
    assert len(calls) == 1 and ledger.status('run')['attempts'][role] == 1
    assert all(a['state'] == 'released' for a in store.records('assignment'))
    assert (Path(request['evidence_dir']) / 'lens-a/original-prompt.txt').read_bytes() == Path(request['prompts'][0]).read_bytes()


@pytest.mark.parametrize('bad_prompt', ['missing', 'directory', 'empty', 'whitespace', 'invalid_utf8', 'nul'])
def test_invalid_second_prompt_has_zero_reservations_debits_or_calls(repository, tmp_path, bad_prompt):
    request, ledger, store, _ = setup_dispatch(repository, tmp_path)
    target = Path(request['prompts'][1])
    if bad_prompt == 'missing':
        target.unlink()
    elif bad_prompt == 'directory':
        target.unlink(); target.mkdir()
    else:
        target.write_bytes({'empty': b'', 'whitespace': b' \r\n\t', 'invalid_utf8': b'\xff', 'nul': b'bad\0prompt'}[bad_prompt])
    with pytest.raises(ValueError, match='prompt'):
        dispatch.execute(request, run=forbidden)
    assert_not_started(request, ledger, store)


def test_all_preprocess_prompt_copies_finish_before_any_debit(repository, tmp_path, monkeypatch):
    request, ledger, store, _ = setup_dispatch(repository, tmp_path)
    original_write = dispatch._write
    def fail_second_preparation(path, payload):
        if path.name == 'schema.json' and path.parent.name == 'lens-b':
            raise OSError('synthetic pre-process setup failure')
        return original_write(path, payload)
    monkeypatch.setattr(dispatch, '_write', fail_second_preparation)
    with pytest.raises(OSError, match='pre-process setup'):
        dispatch.execute(request, run=forbidden)
    assert not ledger.status('run')['attempts'] and not ledger.status('run')['launches']
    assert not store.records('assignment')


def test_prompt_changes_after_admission_do_not_change_native_input(repository, tmp_path, monkeypatch):
    request, ledger, store, manifest = writer_setup(repository, tmp_path)
    original_prompt = Path(request['prompts'][0]).read_bytes()
    original_apply = plan_runtime.Ledger.apply
    def alter_after_admission(self, action, payload):
        admitted = original_apply(self, action, payload)
        if action == 'start':
            Path(request['prompts'][0]).write_text('Injected replacement after debit.\n')
        return admitted
    monkeypatch.setattr(plan_runtime.Ledger, 'apply', alter_after_admission)
    def fake(argv, **kwargs):
        assert original_prompt.decode() in kwargs['input']
        assert 'Injected replacement' not in kwargs['input']
        result = dict(complete=True, coverage_complete=True, truncated=False, findings=[], input_revision=manifest['input_revision'])
        Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(result))
        return SimpleNamespace(returncode=0, stdout='{}\n', stderr='')
    assert dispatch.execute(request, run=fake)['status'] == 'settled'
    assert (Path(request['evidence_dir']) / 'lens-a/original-prompt.txt').read_bytes() == original_prompt


def legacy_bundle(bundle):
    path = bundle / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['schema_version'] = 2
    manifest['input_revision'] = hashlib.sha256(json.dumps(manifest['input_files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    path.chmod(0o600)
    path.write_text(json.dumps(manifest))
    return manifest


def test_plans_dispatch_rejects_legacy_mode_blind_bundle_before_admission(repository, tmp_path):
    request, ledger, store, _ = setup_dispatch(repository, tmp_path)
    old = legacy_bundle(Path(request['bundle']))
    assert evidence.verify(Path(request['bundle']))['schema_version'] == 2  # historical integrity remains supported
    with pytest.raises(ValueError, match='schema 3'):
        dispatch.execute(request, run=forbidden)
    assert_not_started(request, ledger, store)


def test_new_coordination_cleanup_rejects_legacy_mode_blind_retention(repository, tmp_path):
    request, _, store, _ = setup_dispatch(repository, tmp_path)
    root = Path(request['worktree'])
    store.thaw(root, 'fixture')
    claim = store.records('claim')[0]
    store.transition(claim['id'], claim['generation'], claim['session'], 'completed', 'fixture')
    legacy_bundle(Path(request['bundle']))
    inventory = coordination.cleanup_inventory(store, [str(root)], {str(root): {'bundle': request['bundle'], 'originals': []}})
    assert any('schema 3' in reason for reason in inventory['items'][0]['reasons'])
    assert not inventory['items'][0]['eligible']


def test_retained_base_must_equal_immutable_claim_base_before_output(repository, tmp_path):
    request, ledger, store, _ = writer_setup(repository, tmp_path)
    path = Path(request['bundle']) / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['base_commit'] = '0' * 40
    path.chmod(0o600)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='exact owned claim'):
        dispatch.execute(request, run=forbidden)
    assert_not_started(request, ledger, store)


def test_markdown_named_directory_cannot_expand_design_writer_scope(repository, tmp_path):
    relative = f'project/openspec/changes/{CHANGE}/nested.md'
    request, ledger, store, _ = writer_setup(repository, tmp_path, owned=[relative])
    (Path(request['worktree']) / relative).mkdir()
    with pytest.raises(ValueError, match='selected active change'):
        dispatch.execute(request, run=forbidden)
    assert_not_started(request, ledger, store)
