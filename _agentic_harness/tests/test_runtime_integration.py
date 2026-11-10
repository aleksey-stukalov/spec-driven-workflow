"""Offline integration using temporary repositories and fake native/GitHub IO."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import coordination
import dispatch
import evidence
import lifecycle
import plan_runtime

CHANGE = '26-11-09-901-integration-contract'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.PIPE).strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / 'repo'; root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.name', 'Synthetic Test')
    git(root, 'config', 'user.email', 'test@example.invalid')
    (root / 'source.py').write_bytes(b'value = 1\n')
    (root / 'contract.md').write_text('Preserve exact source bytes.\n')
    (root / 'uv.lock').write_text('version = 1\n')
    (root / '.gitignore').write_text('private/\n.venv/\n')
    change = root / 'project' / 'openspec' / 'changes' / CHANGE
    (change / 'specs' / 'synthetic').mkdir(parents=True)
    for name in ['proposal', 'design']:
        (change / (name + '.md')).write_text('# Bounded synthetic contract\n')
    (change / 'tasks.md').write_text('- [ ] Verify implementation\n')
    (change / 'specs' / 'synthetic' / 'spec.md').write_text('## ADDED Requirements\n')
    queue = root / 'project' / 'openspec' / 'queue.yaml'
    queue.write_text(yaml.safe_dump({'queue': [{'change': CHANGE, 'depends_on': []}]}))
    (root / 'project/openspec/config.yaml').write_text('schema: spec-driven\n')
    (root / '_agentic_harness').mkdir()
    (root / '_agentic_harness/projects.yaml').write_text(yaml.safe_dump({'schema_version': 1, 'projects': {'synthetic': {
        'root': 'project', 'queue': 'project/openspec/queue.yaml', 'code_roots': ['project'], 'checks': [['true']],
        'evidence_exclude': ['data/people.csv', 'runtime/state.json'],
        'environment': {'lockfiles': ['uv.lock'], 'prepare': []}}}}))
    git(root, 'add', '.'); git(root, 'commit', '-m', 'synthetic baseline')
    return root


def capture(root, target, scope=None, run_id='run'):
    return evidence.materialize(root, target, scope or ['source.py'], project='synthetic', change=CHANGE,
                                run_id=run_id, base=git(root, 'rev-parse', 'HEAD'), policy='plans-v1')


def test_exact_untracked_source_retained_and_mutations_rejected(repository, tmp_path):
    root = repository
    (root / 'untracked.py').write_bytes(b'new = "\\x00 exact"\n')
    target = tmp_path / 'bundle'
    manifest = capture(root, target, ['source.py', 'untracked.py'])
    assert (target / 'source' / 'untracked.py').read_bytes() == (root / 'untracked.py').read_bytes()
    assert git(root, 'ls-files', 'untracked.py') == ''
    assert evidence.verify(target, root)['input_revision'] == manifest['input_revision']
    (root / 'source.py').write_text('changed live bytes\n')
    assert evidence.verify(target)['input_revision'] == manifest['input_revision']
    with pytest.raises(ValueError, match='current final bytes'): evidence.verify(target, root)
    retained = target / 'source' / 'source.py'; retained.chmod(0o644); retained.write_text('tampered retained bytes\n')
    with pytest.raises(ValueError, match='retained source changed'): evidence.verify(target)


@pytest.mark.parametrize('relative', ['.env', '.env.production', 'data/people.csv', 'runtime/state.json', 'private/ignored.txt', 'key.pem'])
def test_private_or_ignored_source_never_enters_bundle(repository, tmp_path, relative):
    path = repository / relative; path.parent.mkdir(exist_ok=True, parents=True); path.write_text('synthetic private sentinel')
    destination = tmp_path / 'forbidden-bundle'
    with pytest.raises(ValueError, match='private/runtime|ignored source'):
        capture(repository, destination, [relative])
    assert not destination.exists()


def test_capture_alias_and_internal_destination_rejected(repository, tmp_path):
    alias = repository / 'alias.py'; alias.symlink_to(repository / 'source.py')
    with pytest.raises(ValueError, match='aliased'): capture(repository, tmp_path / 'alias-bundle', ['alias.py'])
    with pytest.raises(ValueError, match='fresh external'): capture(repository, repository / 'bundle')
    with pytest.raises(ValueError, match='sorted'): capture(repository, tmp_path / 'wrong-order', ['source.py', 'contract.md'])


def test_design_retained_scope_can_survive_unrelated_commit(repository, tmp_path):
    target = tmp_path / 'design'
    capture(repository, target, ['contract.md'])
    (repository / 'source.py').write_text('new implementation\n')
    git(repository, 'add', 'source.py'); git(repository, 'commit', '-m', 'implementation after design')
    with pytest.raises(ValueError, match='current final bytes'): evidence.verify(target, repository)
    assert evidence.verify(target, repository, current_head_required=False)['input_scope'] == ['contract.md']
    (repository / 'contract.md').write_text('material design change\n')
    with pytest.raises(ValueError, match='current final bytes'): evidence.verify(target, repository, current_head_required=False)


class FakeRemote:
    def __init__(self, *, lose_reply=False, observable=True):
        self.side_effects = 0
        self.lose_reply = lose_reply
        self.observable = observable

    def find(self, item):
        return {'observed': True, 'id': 42} if self.side_effects and self.observable else None

    def perform(self, item):
        self.side_effects += 1
        if self.lose_reply:
            raise TimeoutError('synthetic lost reply after remote mutation')


def operation():
    return dict(action='issue', repo='synthetic/repository', project='synthetic', change=CHANGE,
                title='Bounded synthetic ticket', body='Exact\nmultiline\nbody')


def authority(action='issue', change=CHANGE):
    return dict(source='explicit synthetic user request', project='synthetic', change=change, actions=[action])


def test_lost_github_reply_reconciles_without_duplicate_remote_mutation(tmp_path):
    journal = lifecycle.Journal(tmp_path / 'remote.sqlite')
    journal.prepare('intentional-operation', operation(), authority())
    remote = FakeRemote(lose_reply=True)
    assert journal.execute('intentional-operation', remote)['state'] == 'unknown'
    assert remote.side_effects == 1
    restarted = lifecycle.Journal(tmp_path / 'remote.sqlite')
    assert restarted.execute('intentional-operation', remote)['state'] == 'observed'
    assert remote.side_effects == 1
    assert restarted.execute('intentional-operation', remote)['state'] == 'observed'
    assert remote.side_effects == 1


def test_unknown_unobservable_remote_outcome_does_not_retry(tmp_path):
    journal = lifecycle.Journal(tmp_path / 'remote.sqlite')
    journal.prepare('intentional-operation', operation(), authority())
    remote = FakeRemote(lose_reply=True, observable=False)
    for _ in range(3):
        assert journal.execute('intentional-operation', remote)['state'] == 'unknown'
    assert remote.side_effects == 1


def test_publication_requires_matching_action_and_change_authority(tmp_path):
    journal = lifecycle.Journal(tmp_path / 'remote.sqlite')
    prepared = journal.prepare('operation', operation(), {})
    assert prepared['state'] == 'prepared' and prepared['payload']['body'] == 'Exact\nmultiline\nbody'
    remote = FakeRemote()
    assert 'blocked' in journal.execute('operation', remote) and remote.side_effects == 0
    for wrong in [authority('merge'), authority(change='26-11-09-999-unrelated')]:
        with pytest.raises(ValueError, match='does not cover'): journal.grant('operation', wrong)
    journal.grant('operation', authority())
    assert journal.execute('operation', remote)['state'] == 'observed' and remote.side_effects == 1
    with pytest.raises(ValueError, match='payload changed'):
        journal.prepare('operation', dict(operation(), body='different intentional body'), authority())


def test_remote_creation_uses_exact_body_file_and_reconciliation_marker(repository):
    remote = lifecycle.GhRemote(repository)
    item = {'id': 'operation', 'hash': 'a' * 64, 'payload': operation()}
    seen = []
    def fake_run(argv):
        seen.append((argv, Path(argv[argv.index('--body-file') + 1]).read_text()))
        return 'synthetic result'
    remote.run = fake_run
    remote.perform(item)
    argv, body = seen[0]
    assert argv[:3] == ['gh', 'issue', 'create']
    assert '--body-file' in argv and '--body' not in argv
    assert 'Exact\nmultiline\nbody' in body and lifecycle.GhRemote.marker(item) in body


@pytest.mark.parametrize('provider', ['codex', 'claude'])
def test_native_argv_uses_pinned_supported_settings(provider, tmp_path):
    route = plan_runtime.routes()['steps']['implementation_behavior']['routes'][provider]
    argv = dispatch.command(provider, route, tmp_path, tmp_path, True)
    assert argv[0] == provider and argv[argv.index('--model') + 1] == route['model']
    assert '--max-output-tokens' not in argv and '--temperature' not in argv
    assert '--dangerously-skip-permissions' not in argv and '--yolo' not in argv
    if provider == 'codex':
        assert argv[argv.index('--sandbox') + 1] == 'read-only'
        assert 'model_reasoning_effort="high"' in argv
    else:
        assert argv[argv.index('--effort') + 1] == route['effort']
        assert argv[argv.index('--tools') + 1] == 'Read,Glob,Grep'


def setup_dispatch(repository, tmp_path):
    root = repository
    project = coordination.Project('synthetic', root / 'project', root / 'project/openspec/queue.yaml',
                                   {'lockfiles': ['uv.lock'], 'prepare': []})
    base = git(root, 'rev-parse', 'HEAD')
    worktree = tmp_path / 'workspaces' / 'owned'
    store = coordination.CoordinationStore(root)
    claim = store.claim(project, CHANGE, 'run', 'session', 'lead', 'feat/synthetic', worktree, base, 'explicit fixture')
    coordination.create_workspace(store, claim['id'], claim['generation'], 'session', worktree, worktree.parent,
                                  worktree / '.venv', 'synthetic environment', 'explicit fixture')
    (worktree / 'untracked.py').write_text('new complete review source\n')
    bundle = tmp_path / 'external-source'
    manifest = capture(worktree, bundle, ['source.py', 'untracked.py'])
    store.freeze(worktree, coordination.source_state(worktree)['content_revision'], 'explicit fixture')
    ledger_path = tmp_path / 'ledger.sqlite'
    ledger = plan_runtime.Ledger(ledger_path)
    ledger.init(run_id='run', project='synthetic', change=CHANGE, slices=['owned'], authority={'scope': 'synthetic', 'approved_by': 'fixture'},
                input_revision=manifest['input_revision'], context={}, spend_envelope={'ceiling': None, 'currency': 'unknown', 'unknown_cost_policy': 'retain'}, applicable_steps=[])
    reviewers = []
    for ident, provider, step in [('lens-a', 'codex', 'implementation_behavior'), ('lens-b', 'claude', 'implementation_safety')]:
        route = plan_runtime.routes()['steps'][step]['routes'][provider]
        reviewers.append(dict(launch_id=ident, identity=ident, provider=provider, input_revision=manifest['input_revision'],
                              attestation=dict(source='synthetic capability attestation', supported_models=[route['model']], supported_efforts={route['model']: [route['effort']]}, effective_model=route['model'], effective_effort=route['effort']),
                              context=dict(verified_window=300000, capacity_source='synthetic client', input_tokens=10000, tool_growth_tokens=1000)))
    prompts = []
    for ident in ['a', 'b']:
        path = tmp_path / ('prompt-' + ident + '.txt'); path.write_text('Review every retained source file and the bounded contract.'); prompts.append(str(path))
    intake_path = tmp_path / 'intake.json'
    intake_record = {'schema_version': 1, 'mode': 'review', 'project': 'synthetic', 'change': CHANGE,
        'scope': ['source.py', 'untracked.py'], 'request': {'problem': 'Verify a synthetic change', 'outcome': 'Independent acceptance', 'acceptance': ['Both lenses are clean']},
        'authorities': [{'source': 'user:synthetic-review', 'project': 'synthetic', 'change': CHANGE, 'scope': ['source.py', 'untracked.py'], 'actions': ['review']}], 'ticket': None}
    intake_path.write_text(json.dumps(intake_record))
    intake_ref = {'path': str(intake_path), 'sha256': hashlib.sha256(intake_path.read_bytes()).hexdigest()}
    request = dict(intake=intake_ref, worktree=str(worktree), evidence_dir=str(tmp_path / 'external-results'), bundle=str(bundle), ledger=str(ledger_path), run_id='run', kind='round',
                   coordination=dict(qualified=claim['id'], generation=claim['generation'], session='session', frozen=True, authorization='explicit fixture'), tests=['offline synthetic check'],
                   admission=dict(round_id='I-1', phase='I', input_revision=manifest['input_revision'], reviewers=reviewers), prompts=prompts)
    return request, ledger, store, manifest


def test_fake_native_round_uses_real_durable_admission_coordination_and_originals(repository, tmp_path):
    request, ledger, store, manifest = setup_dispatch(repository, tmp_path)
    calls = []
    result = dict(complete=True, coverage_complete=True, truncated=False, findings=[], input_revision=manifest['input_revision'])
    def fake_native(argv, **kwargs):
        calls.append((argv, kwargs))
        assert Path(kwargs['cwd']) == Path(request['bundle']) / 'source'
        assert (Path(kwargs['cwd']) / 'untracked.py').read_text() == 'new complete review source\n'
        assert manifest['input_revision'] in kwargs['input']
        if argv[0] == 'codex':
            Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(result))
            return SimpleNamespace(returncode=0, stdout=json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 123}}) + '\n', stderr='')
        return SimpleNamespace(returncode=0, stdout=json.dumps({'structured_output': result, 'usage': {'input_tokens': 321}, 'total_cost_usd': 1.25}), stderr='')
    returned = dispatch.execute(request, run=fake_native)
    assert returned['status'] == 'settled' and len(calls) == 2
    state = ledger.status('run')
    assert len(state['rounds']) == 1 and state['rounds'][0]['clean']
    assert len(state['launches']) == 2 and len(state['usage']) == 2
    assert sorted(u['record']['cost'] or 0 for u in state['usage']) == [0, 1.25]
    assert all(v['effective']['actual'] == {'model': None, 'effort': None} for v in state['launches'].values())
    assert ledger.gate(run_id='run', phase='I', input_revision=manifest['input_revision'], checks_passed=True)['accepted']
    assert all(a['state'] == 'released' for a in store.records('assignment'))
    for ident in ['lens-a', 'lens-b']:
        folder = Path(request['evidence_dir']) / ident
        assert json.loads((folder / 'original-result.json').read_text()) == result
        assert (folder / 'stdout.txt').exists() and (folder / 'prompt.txt').exists()
    replay = dict(request, evidence_dir=str(tmp_path / 'replay-results'))
    with pytest.raises(ValueError, match='already admitted'): dispatch.execute(replay, run=fake_native)
    assert len(calls) == 2 and not Path(replay['evidence_dir']).exists()


def test_unknown_provider_outcome_stays_charged_and_unreleased(repository, tmp_path):
    request, ledger, store, manifest = setup_dispatch(repository, tmp_path)
    calls = []
    def lost_reply(argv, **kwargs):
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, 1)
    returned = dispatch.execute(request, run=lost_reply)
    assert returned['status'] == 'incomplete' and len(calls) == 2
    state = ledger.status('run')
    assert len(state['rounds']) == 1 and all(v['status'] == 'uncertain' for v in state['launches'].values())
    assert len(state['usage']) == 2 and all(u['record']['cost'] is None for u in state['usage'])
    assert all(a['state'] == 'running' for a in store.records('assignment'))
    assert not ledger.gate(run_id='run', phase='I', input_revision=manifest['input_revision'], checks_passed=True)['accepted']
    with pytest.raises(ValueError, match='already admitted'):
        dispatch.execute(dict(request, evidence_dir=str(tmp_path / 'replay')), run=lost_reply)
    assert len(calls) == 2


def test_revision_mismatch_blocks_before_reservation_or_provider(repository, tmp_path):
    request, ledger, store, manifest = setup_dispatch(repository, tmp_path)
    request['admission']['input_revision'] = 'wrong source'
    def forbidden(*args, **kwargs):
        pytest.fail('provider must never start on mismatched inputs')
    with pytest.raises(ValueError, match='admission revision'):
        dispatch.execute(request, run=forbidden)
    assert not ledger.status('run')['launches'] and not store.records('assignment')
    assert not Path(request['evidence_dir']).exists()


@pytest.mark.parametrize('bad_stdout', ['[]', 'null', 'true'])
def test_malformed_claude_transport_returns_controlled_uncertain(tmp_path, bad_stdout):
    directory = tmp_path / 'attempt'; directory.mkdir()
    route = plan_runtime.routes()['steps']['implementation_safety']['routes']['claude']
    launch = dict(provider='claude', effective={'requested': route, 'permitted_writes': 'read_only'})
    def malformed(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=bad_stdout, stderr='')
    status, result, usage = dispatch._provider(launch, 'Review retained inputs.', tmp_path, directory, run=malformed)
    assert status == 'uncertain' and result['outcome'] == 'unknown'
    assert usage['cost'] is None and (directory / 'stdout.txt').read_text() == bad_stdout


def test_second_lens_invalid_preflight_releases_unlaunched_coordination_reservations(repository, tmp_path):
    request, ledger, store, _ = setup_dispatch(repository, tmp_path)
    request['admission']['reviewers'][1]['attestation']['supported_models'] = []
    def forbidden(*args, **kwargs):
        pytest.fail('provider must never launch after failed atomic admission')
    with pytest.raises(ValueError, match='unavailable'):
        dispatch.execute(request, run=forbidden)
    assert ledger.status('run')['launches'] == {} and ledger.status('run')['rounds'] == []
    assert all(a['state'] == 'released' for a in store.records('assignment'))
    for ident in ['lens-a', 'lens-b']:
        record = json.loads((Path(request['evidence_dir']) / ident / 'not-launched.json').read_text())
        assert record['status'] == 'not-launched'


@pytest.mark.parametrize('bad_id', ['../escape', '/absolute-escape', 'nested/escape', '..'])
def test_unsafe_launch_identity_blocks_before_external_evidence_write(repository, tmp_path, bad_id):
    request, ledger, store, _ = setup_dispatch(repository, tmp_path)
    request['admission']['reviewers'][0]['launch_id'] = bad_id
    def forbidden(*args, **kwargs):
        pytest.fail('provider must never launch on unsafe filesystem identity')
    with pytest.raises(ValueError, match='launch|identity'):
        dispatch.execute(request, run=forbidden)
    assert not Path(request['evidence_dir']).exists()
    assert ledger.status('run')['launches'] == {} and not store.records('assignment')


@pytest.mark.parametrize('bad_event', ['null', '[]', '1'])
def test_malformed_codex_jsonl_returns_controlled_uncertain(tmp_path, bad_event):
    directory = tmp_path / 'attempt'; directory.mkdir()
    route = plan_runtime.routes()['steps']['implementation_behavior']['routes']['codex']
    launch = dict(provider='codex', effective={'requested': route, 'permitted_writes': 'read_only'})
    def malformed(argv, **kwargs):
        Path(argv[argv.index('--output-last-message') + 1]).write_text('{}')
        return SimpleNamespace(returncode=0, stdout=bad_event + '\n', stderr='')
    status, result, usage = dispatch._provider(launch, 'Review retained inputs.', tmp_path, directory, run=malformed)
    assert status == 'uncertain' and result['outcome'] == 'unknown'
    assert usage['cost'] is None


def reference(path, value):
    path.write_text(json.dumps(value))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def test_original_launch_recovery_settles_coordinator_without_replay(repository, tmp_path):
    request, ledger, store, manifest = setup_dispatch(repository, tmp_path)
    calls = []
    def interrupted(argv, **kwargs):
        calls.append(argv)
        raise TimeoutError('lost process outcome')
    assert dispatch.execute(request, run=interrupted)['status'] == 'incomplete'
    assert len(calls) == 2
    for number, launch_id in enumerate(['lens-a', 'lens-b']):
        report = reference(tmp_path / (launch_id + '-original.json'), dict(complete=True, coverage_complete=True, truncated=False, findings=[], input_revision=manifest['input_revision']))
        usage = reference(tmp_path / (launch_id + '-usage.json'), {'cost': 0.1})
        process = reference(tmp_path / (launch_id + '-stopped.json'), dict(run_id='run', launch_id=launch_id,
            input_revision=manifest['input_revision'], process_stopped=True, status='success', source='synthetic stopped-process observation',
            original_result_sha256=report['sha256'], usage_sha256=usage['sha256']))
        recovery = dict(run_id='run', launch_id=launch_id, receipt_id=launch_id + '-recovered', status='success',
            original_result=report, process_evidence=process, authority={'scope': 'synthetic', 'approved_by': 'fixture', 'source': 'user:reconcile'},
            usage_reference=usage, usage_complete=True)
        recovered = dispatch.recover({'ledger': request['ledger'], 'worktree': request['worktree'], 'recovery': recovery})
        assert len(recovered['unsettled_siblings']) == 1 - number
        # An identical receipt is reconciliation, never another provider execution.
        dispatch.recover({'ledger': request['ledger'], 'worktree': request['worktree'], 'recovery': recovery})
    assert len(calls) == 2
    assert all(a['state'] == 'released' for a in store.records('assignment'))
    assert len(ledger.status('run')['rounds']) == 1
    assert ledger.gate(run_id='run', phase='I', input_revision=manifest['input_revision'], checks_passed=True)['accepted']


def test_dispatch_rejects_missing_or_tampered_intake_before_admission(repository, tmp_path):
    request, ledger, store, manifest = setup_dispatch(repository, tmp_path)
    Path(request['intake']['path']).write_text('{}')
    with pytest.raises(ValueError, match='original evidence hash mismatch'):
        dispatch.execute(request, run=lambda *a, **k: pytest.fail('must not launch'))
    assert not Path(request['evidence_dir']).exists()
    assert not ledger.status('run')['launches']
