"""Explicit lock/environment rebind preserves ownership, counters and recovery."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_runtime_integration import repository, setup_dispatch, reference, coordination


def prepared(repository, tmp_path):
    request, ledger, store, _ = setup_dispatch(repository, tmp_path)
    root = Path(request['worktree'])
    store.thaw(root, 'fixture:prepare-dependency-edit')
    claim = store.records('claim')[0]
    (root / 'uv.lock').write_text('version = 1\nrevision = 2\n')
    environment = root / '.venv'
    environment.mkdir()
    current = coordination.source_state(root)
    receipt = dict(schema_version=2, kind='environment-preparation', receipt_id='preparation-1', verified=True,
                   repository_id=store.repository_id, project=claim['project'], change=claim['change'],
                   run=claim['run'], session=claim['session'], worktree=str(root), branch=claim['branch'],
                   base_revision=claim['base_revision'], environment=str(environment),
                   environment_policy=claim['environment_policy'],
                   lockfiles=coordination.lock_inventory(root, claim['environment_policy']), expected_source=current)
    original = tmp_path / 'environment-preparation.json'
    locator = reference(original, receipt)
    payload = dict(qualified=claim['id'], generation=claim['generation'], session=claim['session'],
                   authority=dict(source='user:authorized-dependency-rebind', project=claim['project'],
                                  change=claim['change'], run=claim['run'], session=claim['session'], actions=['rebind-environment']),
                   expected_source=current, preparation=locator)
    return root, ledger, store, claim, receipt, payload


def test_rebind_enables_post_dependency_edit_review_and_resume_without_reset(repository, tmp_path):
    root, ledger, store, claim, receipt, payload = prepared(repository, tmp_path)
    original_claim = deepcopy(store.get_claim(claim['id']))
    original_run = ledger.status('run')
    with pytest.raises(ValueError, match='lock changed'):
        coordination._inspect_workspace(store, store.records('workspace')[0])
    result = coordination.rebind_environment(store, **payload)
    assert not result['replayed']
    assert result['prior']['lockfiles'] != result['current']['lockfiles']
    assert result['current']['lockfiles'] == receipt['lockfiles']
    workspace = store.records('workspace')[0]
    assert workspace['environment_history'] == [{k: v for k, v in result.items() if k != 'replayed'}]
    assert coordination._inspect_workspace(store, workspace) == payload['expected_source']
    assert store.get_claim(claim['id']) == original_claim
    assert ledger.status('run') == original_run
    replay = coordination.rebind_environment(store, **payload)
    assert replay['replayed'] and replay['prior'] == result['prior']
    assert len(store.records('workspace')[0]['environment_history']) == 1
    # The dirty dependency edit is reconciled, rather than discarded or blessed
    # as a successful implementation merely because its environment was prepared.
    resumed = coordination.resume_workspace(store, claim['id'], claim['generation'], claim['session'],
        'user:resume-owned-dependency-edit', payload['expected_source'],
        dict(original_results='evidence:retained', budget_ledger='ledger:unchanged', decisions='decision:dependency-edit', operation_receipts='receipts:unchanged'))
    assert resumed['expected_source'] == payload['expected_source']
    assert store.freeze(root, payload['expected_source']['content_revision'], 'user:post-fix-review')['active']
    assert ledger.status('run') == original_run


@pytest.mark.parametrize('kind', ['import', 'live', 'environment', 'resume'])
def test_active_dependency_pins_block_rebind(repository, tmp_path, kind):
    root, _, store, _, _, payload = prepared(repository, tmp_path)
    store.pin(root / '.venv', kind, f'{kind}:still-owned', 'fixture')
    before = deepcopy(store.records('workspace'))
    with pytest.raises(ValueError, match='pin prevents'):
        coordination.rebind_environment(store, **payload)
    assert store.records('workspace') == before


def test_frozen_review_blocks_environment_rebind(repository, tmp_path):
    root, _, store, _, _, payload = prepared(repository, tmp_path)
    store.freeze(root, payload['expected_source']['content_revision'], 'fixture:review')
    with pytest.raises(ValueError, match='frozen review'):
        coordination.rebind_environment(store, **payload)


def test_assignments_must_settle_and_release_before_rebind(repository, tmp_path):
    root, _, store, claim, _, payload = prepared(repository, tmp_path)
    store.reserve(claim['id'], claim['generation'], claim['session'], 'writer-1', claim['run'], ['uv.lock'],
                  payload['expected_source']['content_revision'], ['offline dependency check'], str(tmp_path / 'writer-output'), 'fixture')
    with pytest.raises(ValueError, match='settle and release'):
        coordination.rebind_environment(store, **payload)
    original = tmp_path / 'writer-original.json'
    original.write_text('{"complete":true}')
    store.settle('writer-1', str(original), 'fixture')
    with pytest.raises(ValueError, match='settle and release'):
        coordination.rebind_environment(store, **payload)
    store.release_assignments(claim['run'], 'fixture')
    assert not coordination.rebind_environment(store, **payload)['replayed']


@pytest.mark.parametrize('field,value', [
    ('project', 'other-project'), ('change', '26-11-09-999-another-change'), ('run', 'another-run'),
    ('session', 'other-session'), ('worktree', '/wrong-worktree'), ('branch', 'feat/wrong'),
    ('base_revision', '0' * 40), ('lockfiles', {'uv.lock': '0' * 64}), ('verified', False),
])
def test_mismatched_preparation_cannot_change_binding(repository, tmp_path, field, value):
    _, _, store, _, receipt, payload = prepared(repository, tmp_path)
    receipt[field] = value
    payload['preparation'] = reference(Path(payload['preparation']['path']), receipt)
    before = deepcopy(store.records('workspace'))
    with pytest.raises(ValueError):
        coordination.rebind_environment(store, **payload)
    assert store.records('workspace') == before
    assert not store.records('environment-rebind')


@pytest.mark.parametrize('failure', ['missing_original', 'changed_original', 'stale_source', 'outside_environment', 'wrong_authority', 'old_generation'])
def test_unverified_or_stale_preparation_and_authority_block(repository, tmp_path, failure):
    root, _, store, _, receipt, payload = prepared(repository, tmp_path)
    path = Path(payload['preparation']['path'])
    if failure == 'missing_original':
        path.unlink()
    elif failure == 'changed_original':
        path.write_text(path.read_text() + ' ')
    elif failure == 'stale_source':
        (root / 'source.py').write_text('newer unreviewed content\n')
    elif failure == 'outside_environment':
        receipt['environment'] = str(tmp_path)
        payload['preparation'] = reference(path, receipt)
    elif failure == 'wrong_authority':
        payload['authority']['actions'] = ['implementation']
    else:
        payload['generation'] += 1
    with pytest.raises(ValueError):
        coordination.rebind_environment(store, **payload)
    assert not store.records('environment-rebind')


def test_receipt_identity_reuse_with_changed_bytes_is_rejected(repository, tmp_path):
    _, _, store, _, receipt, payload = prepared(repository, tmp_path)
    coordination.rebind_environment(store, **payload)
    other = tmp_path / 'same-id-new-reference.json'
    payload['preparation'] = reference(other, receipt)
    with pytest.raises(ValueError, match='identity conflicts'):
        coordination.rebind_environment(store, **payload)
    assert len(store.records('workspace')[0]['environment_history']) == 1


def test_rebind_cli_uses_same_owned_receipt_validation(repository, tmp_path):
    root, _, store, _, _, payload = prepared(repository, tmp_path)
    request_file = tmp_path / 'rebind-request.json'
    request_file.write_text(json.dumps(payload))
    completed = subprocess.run([sys.executable, coordination.__file__, 'rebind-environment', '--repository', str(root),
                                '--request', str(request_file)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)['result']['current']['lockfiles'] == store.records('workspace')[0]['lockfiles']


def test_original_inside_other_linked_checkout_is_not_external(repository, tmp_path):
    _, _, store, _, receipt, payload = prepared(repository, tmp_path)
    payload['preparation'] = reference(repository / 'preparation-original.json', receipt)
    with pytest.raises(ValueError, match='external to every linked worktree'):
        coordination.rebind_environment(store, **payload)
    assert not store.records('environment-rebind')
