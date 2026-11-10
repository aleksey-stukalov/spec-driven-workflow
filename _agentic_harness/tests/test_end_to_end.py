"""One interrupted synthetic run, repair, fresh acceptance and safe cleanup."""
import copy
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

from test_runtime_integration import (
    repository, setup_dispatch, reference, capture, git, FakeRemote, operation,
    authority, coordination, dispatch, evidence, lifecycle, plan_runtime,
)


def test_interrupted_review_repair_remote_reconcile_and_cleanup(repository, tmp_path):
    request, ledger, store, initial = setup_dispatch(repository, tmp_path)
    root = Path(request['worktree'])
    barrier = threading.Barrier(2)
    calls = []

    def report(revision, findings=None):
        return dict(complete=True, coverage_complete=True, truncated=False,
                    findings=findings or [], input_revision=revision)

    def initial_provider(argv, **kwargs):
        calls.append(argv[0])
        barrier.wait(timeout=10)
        if argv[0] == 'claude':
            raise TimeoutError('stopped process returned after transport loss')
        result = report(initial['input_revision'], [dict(id='F1', severity='major', summary='value must be 2')])
        Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(result))
        return SimpleNamespace(returncode=0, stdout='{}\n', stderr='')

    assert dispatch.execute(request, run=initial_provider)['status'] == 'incomplete'
    assert len(calls) == 2
    result_ref = reference(tmp_path / 'recovered-result.json', report(initial['input_revision']))
    usage_ref = reference(tmp_path / 'recovered-usage.json', {'cost': 0.1})
    stopped_ref = reference(tmp_path / 'stopped.json', dict(run_id='run', launch_id='lens-b',
        input_revision=initial['input_revision'], process_stopped=True, status='success',
        source='synthetic stopped-process observation', original_result_sha256=result_ref['sha256'], usage_sha256=usage_ref['sha256']))
    recovery = dict(run_id='run', launch_id='lens-b', receipt_id='recovered-b', status='success',
        original_result=result_ref, process_evidence=stopped_ref,
        authority={'scope':'synthetic', 'approved_by':'fixture', 'source':'user:reconcile'},
        usage_reference=usage_ref, usage_complete=True)
    dispatch.recover({'ledger':request['ledger'], 'worktree':str(root), 'recovery':recovery})
    assert not ledger.gate(run_id='run', phase='I', input_revision=initial['input_revision'], checks_passed=True)['accepted']
    assert all(a['state'] == 'released' for a in store.records('assignment'))
    assert store.thaw(root, 'fixture')['valid']

    route = plan_runtime.routes()['steps']['implementation_fixer']['routes']['codex']
    ledger.start(run_id='run', launch_id='repair', identity='repair', step='implementation_fixer',
        provider='codex', input_revision=initial['input_revision'], owned_paths=['source.py'],
        attestation={'source':'synthetic capability', 'supported_models':[route['model']],
                     'supported_efforts':{route['model']:[route['effort']]},
                     'effective_model':route['model'], 'effective_effort':route['effort']},
        context={'verified_window':300000, 'capacity_source':'synthetic', 'input_tokens':10000, 'tool_growth_tokens':1000})
    claim = store.records('claim')[0]
    original = tmp_path / 'repair-original.json'
    store.reserve(claim['id'], claim['generation'], 'session', 'repair', 'run', ['source.py'],
        coordination.source_state(root)['content_revision'], ['synthetic value check'], str(original), 'fixture', 'writer')
    (root / 'source.py').write_text('value = 2\n')
    result = report(initial['input_revision'])
    reference(original, result)
    ledger.finish(run_id='run', launch_id='repair', status='success', result=result, usage={'cost':0.1})
    store.settle('repair', str(original), 'fixture')
    store.release_assignments('run', 'fixture')
    assert (root / 'source.py').read_text() == 'value = 2\n'
    git(root, 'add', 'source.py', 'untracked.py')
    git(root, 'commit', '-m', 'synthetic confirmed repair')

    final_bundle = tmp_path / 'final-source'
    final = evidence.materialize(root, final_bundle, initial['input_scope'],
        project='synthetic', change=initial['change'], run_id='run',
        base=claim['base_revision'], policy='plans-v1')
    manifest_path = final_bundle / 'manifest.json'
    ledger.reconcile(run_id='run', input_revision=final['input_revision'], phase_revisions={'I':final['input_revision']},
        reason='Confirmed F1 repair; original round retained', snapshot_references={'I':{
            'path':str(manifest_path), 'sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest()}})
    store.freeze(root, coordination.source_state(root)['content_revision'], 'fixture')
    final_request = copy.deepcopy(request)
    final_request.update(bundle=str(final_bundle), evidence_dir=str(tmp_path / 'final-results'))
    final_request['admission'].update(round_id='I-2', input_revision=final['input_revision'])
    for reviewer in final_request['admission']['reviewers']:
        reviewer.update(launch_id=reviewer['launch_id']+'-fresh', identity=reviewer['identity']+'-fresh', input_revision=final['input_revision'])

    def final_provider(argv, **kwargs):
        calls.append(argv[0])
        assert Path(kwargs['cwd']) == final_bundle / 'source'
        result = report(final['input_revision'])
        if argv[0] == 'codex':
            Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(result))
            return SimpleNamespace(returncode=0, stdout='{}\n', stderr='')
        return SimpleNamespace(returncode=0, stdout=json.dumps({'structured_output':result, 'total_cost_usd':0.1}), stderr='')

    dispatch.execute(final_request, run=final_provider)
    ledger.dispute(run_id='run', finding_id='F1', severity='major', status='resolved',
        evidence='synthetic assertion and both fresh reviewers accept value=2', independent_round_id='I-2')
    ledger = plan_runtime.Ledger(Path(request['ledger']))
    assert ledger.gate(run_id='run', phase='I', input_revision=final['input_revision'], checks_passed=True)['accepted']
    assert len(ledger.status('run')['rounds']) == 2
    assert len(ledger.status('run')['launches']) == 5
    assert ledger.status('run')['attempts']['implementation_fixer'] == 1
    assert len(calls) == 4
    evidence.verify(final_bundle, root)

    journal_path = tmp_path / 'remote.sqlite'
    journal = lifecycle.Journal(journal_path)
    journal.prepare('synthetic-ticket', operation(), authority())
    remote = FakeRemote(lose_reply=True)
    assert journal.execute('synthetic-ticket', remote)['state'] == 'unknown'
    assert lifecycle.Journal(journal_path).execute('synthetic-ticket', remote)['state'] == 'observed'
    assert remote.side_effects == 1

    assert store.thaw(root, 'fixture')['valid']
    store.transition(claim['id'], claim['generation'], 'session', 'completed', 'fixture')
    refs = []
    for assignment in store.records('assignment'):
        path = Path(assignment['result_reference'])
        refs.append({'path':str(path), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    retained = {str(root):{'bundle':str(final_bundle), 'originals':refs}}
    inventory = coordination.cleanup_inventory(store, [str(root)], retained)
    assert inventory['items'][0]['eligible']
    pin = store.pin(root / '.venv', 'import', 'synthetic resumable import', 'fixture')
    assert not coordination.apply_cleanup(store, inventory, 'user:exact-cleanup')[0]['removed']
    store.unpin(pin['id'], 'synthetic import stopped')
    inventory = coordination.cleanup_inventory(store, [str(root)], retained)
    assert coordination.apply_cleanup(store, inventory, 'user:exact-cleanup')[0]['removed']
    assert not root.exists() and (final_bundle / 'source/source.py').read_text() == 'value = 2\n'
    assert git(repository, 'rev-parse', 'feat/synthetic') == final['input_head']
