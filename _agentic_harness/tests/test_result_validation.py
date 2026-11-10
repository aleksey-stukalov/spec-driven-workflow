"""Stopped native workers cannot satisfy completion with malformed reports."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import dispatch
import plan_runtime


REVISION = 'a' * 64
RUN = 'result-validation'
SCOPE = 'synthetic result validation only'


def complete_result(**changes):
    return dict(complete=True, coverage_complete=True, truncated=False, findings=[],
                input_revision=REVISION, **changes)


def invalid_reports():
    cases = [('only-complete', {'complete': True}), ('empty-object', {})]
    for key in ('complete', 'coverage_complete', 'truncated', 'findings', 'input_revision'):
        value = complete_result()
        del value[key]
        cases.append(('missing-' + key, value))
    for key, value in [
        ('complete', 1), ('coverage_complete', 'true'), ('truncated', 0),
        ('findings', {}), ('findings', ['not-a-finding']),
        ('findings', [{'severity': 'major'}]),
        ('input_revision', 'b' * 64), ('input_revision', 17),
        ('complete', False), ('coverage_complete', False), ('truncated', True),
    ]:
        report = complete_result()
        report[key] = value
        cases.append((key + '-' + json.dumps(value, sort_keys=True), report))
    cases.extend([('null-result', None), ('array-result', []),
                  ('string-result', 'complete'), ('boolean-result', True)])
    return [pytest.param(report, id=name) for name, report in cases]


INVALID_REPORTS = invalid_reports()


def assignment(step, identity, provider='codex'):
    route = plan_runtime.routes()['steps'][step]['routes'][provider]
    return dict(launch_id=identity, identity=identity, provider=provider,
                input_revision=REVISION,
                attestation={'source': 'synthetic account observation',
                             'supported_models': [route['model']],
                             'supported_efforts': {route['model']: [route['effort']]},
                             'effective_model': route['model'], 'effective_effort': route['effort']},
                context={'verified_window': 300000, 'capacity_source': 'synthetic client',
                         'input_tokens': 10000, 'tool_growth_tokens': 1000})


def writer_ledger(tmp_path, provider='codex'):
    ledger = plan_runtime.Ledger(tmp_path / 'ledger.sqlite')
    ledger.init(run_id=RUN, project='example', change='26-11-10-901-result-validation',
                plan='balanced', slices=['source'],
                authority={'scope': SCOPE, 'approved_by': 'test fixture'},
                input_revision=REVISION, context={}, applicable_steps=['implementer'],
                spend_envelope={'ceiling': None, 'currency': 'unknown', 'unknown_cost_policy': 'retain'})
    request = dict(run_id=RUN, step='implementer', slice_id='source',
                   owned_paths=['source.py'], **assignment('implementer', 'writer', provider))
    launch = ledger.start(**request)['launch']
    return ledger, request, launch


def clean_review(ledger):
    reviewers = [assignment(step, 'reviewer-' + str(index))
                 for index, step in enumerate(plan_runtime.REVIEW_STEPS['I'])]
    started = ledger.start_round(run_id=RUN, round_id='final-review', phase='I',
                                 input_revision=REVISION, reviewers=reviewers)
    for launch in started['launches']:
        ledger.finish(run_id=RUN, launch_id=launch['launch_id'], status='success',
                      result=complete_result(), usage={'cost': None})
    assert ledger.status(RUN)['rounds'][-1]['clean']


def gate(ledger):
    return ledger.gate(run_id=RUN, phase='I', input_revision=REVISION, checks_passed=True)


def native_transport(report, calls):
    """Only substitute native IO; use real parsing, retention and ledger logic."""
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[0] == 'codex':
            path = Path(argv[argv.index('--output-last-message') + 1])
            path.write_text(json.dumps(report))
            return SimpleNamespace(returncode=0,
                                   stdout='{"type":"turn.completed","usage":{"input_tokens":12}}\n',
                                   stderr='synthetic stopped process\n')
        return SimpleNamespace(returncode=0,
                               stdout=json.dumps({'structured_output': report,
                                                  'usage': {'input_tokens': 12}, 'total_cost_usd': 0.1}),
                               stderr='synthetic stopped process\n')
    return run


@pytest.mark.parametrize('provider', ['codex', 'claude'])
@pytest.mark.parametrize('report', INVALID_REPORTS)
def test_stopped_invalid_native_writer_stays_charged_but_cannot_complete(tmp_path, provider, report):
    ledger, request, launch = writer_ledger(tmp_path, provider)
    directory = tmp_path / 'native-originals'
    directory.mkdir()
    calls = []
    status, original, usage = dispatch._provider(
        launch, 'Implement the assigned source and report complete coverage.', tmp_path,
        directory, run=native_transport(report, calls))
    assert status == 'incomplete'
    assert original == report
    assert json.loads((directory / 'original-result.json').read_text()) == report
    assert (directory / 'stderr.txt').read_text() == 'synthetic stopped process\n'
    assert not (directory / 'uncertain.json').exists()
    assert len(calls) == 1
    settled = ledger.finish(run_id=RUN, launch_id='writer', status=status, result=original, usage=usage)
    assert settled['launch']['status'] == 'incomplete'
    state = ledger.status(RUN)
    assert state['attempts']['implementer:source'] == 1
    assert state['launches']['writer']['result'] == report
    assert len(state['usage']) == 1
    assert all(item['status'] not in plan_runtime.ACTIVE for item in state['launches'].values())
    assert ledger.start(**request)['replayed']
    assert len(calls) == 1 and ledger.status(RUN)['attempts']['implementer:source'] == 1
    clean_review(ledger)
    verdict = gate(ledger)
    assert not verdict['accepted']
    assert verdict['clean_streak'] == 1
    assert 'missing_successful_step:implementer:source' in verdict['blockers']
    assert 'workers_unsettled' not in verdict['blockers']


@pytest.mark.parametrize('provider', ['codex', 'claude'])
def test_valid_native_writer_and_independent_clean_review_can_complete(tmp_path, provider):
    ledger, _, launch = writer_ledger(tmp_path, provider)
    directory = tmp_path / 'native-originals'
    directory.mkdir()
    calls = []
    report = complete_result(summary='The implementation and its verification are complete.')
    status, original, usage = dispatch._provider(
        launch, 'Implement the assigned source.', tmp_path, directory,
        run=native_transport(report, calls))
    assert status == 'success' and original == report and len(calls) == 1
    ledger.finish(run_id=RUN, launch_id='writer', status=status, result=original, usage=usage)
    clean_review(ledger)
    assert gate(ledger)['accepted']


@pytest.mark.parametrize('provider', ['codex', 'claude'])
@pytest.mark.parametrize('malformation', ['duplicate-required-key', 'nonfinite-extra-value'])
def test_stopped_native_json_with_ambiguous_or_nonfinite_values_is_incomplete(tmp_path, provider, malformation):
    ledger, _, launch = writer_ledger(tmp_path, provider)
    directory = tmp_path / 'native-originals'
    directory.mkdir()
    raw = json.dumps(complete_result())
    if malformation == 'duplicate-required-key':
        raw = raw.replace('"complete": true', '"complete": false, "complete": true', 1)
    else:
        raw = raw[:-1] + ', "measurement": NaN}'
    calls = []
    stdout = '{}\n' if provider == 'codex' else '{"structured_output":' + raw + '}'

    def malformed_native(argv, **kwargs):
        calls.append(argv)
        if provider == 'codex':
            Path(argv[argv.index('--output-last-message') + 1]).write_text(raw)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr='')

    status, original, usage = dispatch._provider(
        launch, 'Implement the assigned source.', tmp_path, directory, run=malformed_native)
    assert status == 'incomplete' and original is None
    assert (directory / 'stdout.txt').read_text() == stdout
    if provider == 'codex':
        assert (directory / 'native-result.json').read_text() == raw
    assert json.loads((directory / 'original-result.json').read_text()) is None
    assert not (directory / 'uncertain.json').exists()
    assert len(calls) == 1
    ledger.finish(run_id=RUN, launch_id='writer', status=status, result=original, usage=usage)
    assert ledger.status(RUN)['attempts']['implementer:source'] == 1
    assert ledger.status(RUN)['launches']['writer']['status'] == 'incomplete'


@pytest.mark.parametrize('report', INVALID_REPORTS)
def test_direct_finish_cannot_assert_success_for_an_invalid_writer_result(tmp_path, report):
    ledger, _, _ = writer_ledger(tmp_path)
    receipt = ledger.finish(run_id=RUN, launch_id='writer', status='success', result=report, usage={'cost': None})
    assert receipt['launch']['status'] == 'incomplete'
    assert receipt['launch']['result'] == report
    clean_review(ledger)
    assert 'missing_successful_step:implementer:source' in gate(ledger)['blockers']


@pytest.mark.parametrize('report', [
    {'complete': True},
    dict(complete_result(), coverage_complete=1),
    dict(complete_result(), findings=['invalid']),
    dict(complete_result(), input_revision='old-revision'),
])
def test_gate_revalidates_legacy_success_records_without_trusting_status(tmp_path, report):
    ledger, _, _ = writer_ledger(tmp_path)
    ledger.finish(run_id=RUN, launch_id='writer', status='success', result=complete_result(), usage={'cost': None})
    clean_review(ledger)
    assert gate(ledger)['accepted']
    with sqlite3.connect(ledger.path) as connection:
        row = connection.execute('SELECT body FROM runs WHERE id=?', (RUN,)).fetchone()
        state = json.loads(row[0])
        state['launches']['writer'].update(status='success', result=report)
        connection.execute('UPDATE runs SET body=? WHERE id=?', (json.dumps(state), RUN))
    resumed = plan_runtime.Ledger(ledger.path)
    verdict = gate(resumed)
    assert not verdict['accepted'] and verdict['clean_streak'] == 1
    assert 'missing_successful_step:implementer:source' in verdict['blockers']


def reference(path, value):
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def test_stopped_recovery_preserves_incomplete_original_without_fulfilling_writer_minimum(tmp_path):
    ledger, request, _ = writer_ledger(tmp_path)
    ledger.finish(run_id=RUN, launch_id='writer', status='uncertain',
                  result={'outcome': 'unknown'}, usage={'cost': None})
    report = dict(complete_result(), coverage_complete=False)
    result_ref = reference(tmp_path / 'recovered-result.json', report)
    usage_ref = reference(tmp_path / 'recovered-usage.json', {'cost': 0.1})
    process_ref = reference(tmp_path / 'stopped-process.json', {
        'run_id': RUN, 'launch_id': 'writer', 'input_revision': REVISION,
        'process_stopped': True, 'status': 'success', 'source': 'synthetic stopped native process',
        'original_result_sha256': result_ref['sha256'], 'usage_sha256': usage_ref['sha256'],
    })
    recovery = dict(run_id=RUN, launch_id='writer', receipt_id='recovered-writer', status='success',
                    original_result=result_ref, process_evidence=process_ref, usage_reference=usage_ref,
                    usage_complete=True,
                    authority={'approved_by': 'test fixture', 'scope': SCOPE, 'source': 'user:reconcile-worker'})
    receipt = ledger.recover_launch(**recovery)
    assert receipt['launch']['status'] == 'incomplete'
    assert receipt['launch']['result'] == report
    assert receipt['recovery']['resolved_status'] == 'incomplete'
    assert ledger.status(RUN)['attempts']['implementer:source'] == 1
    assert ledger.start(**request)['replayed']
    assert ledger.recover_launch(**recovery)['replayed']
    clean_review(ledger)
    assert 'missing_successful_step:implementer:source' in gate(ledger)['blockers']


def test_completed_review_with_a_valid_finding_cannot_count_as_clean(tmp_path):
    ledger, _, _ = writer_ledger(tmp_path)
    ledger.finish(run_id=RUN, launch_id='writer', status='success', result=complete_result(), usage={'cost': None})
    reviewers = [assignment(step, 'reviewer-' + str(index))
                 for index, step in enumerate(plan_runtime.REVIEW_STEPS['I'])]
    launches = ledger.start_round(run_id=RUN, round_id='findings-review', phase='I',
                                   input_revision=REVISION, reviewers=reviewers)['launches']
    for index, launch in enumerate(launches):
        report = complete_result()
        if index == 0:
            report['findings'] = [{'id': 'F1', 'severity': 'minor', 'summary': 'A documented edge case is missing.'}]
        receipt = ledger.finish(run_id=RUN, launch_id=launch['launch_id'], status='success', result=report, usage={'cost': None})
        assert receipt['launch']['status'] == 'success'
    state = ledger.status(RUN)
    assert state['rounds'][-1]['status'] == 'complete'
    assert not state['rounds'][-1]['clean']
    assert 'insufficient_clean_rounds' in gate(ledger)['blockers']


@pytest.mark.parametrize('provider', ['codex', 'claude'])
def test_dispatch_releases_stopped_incomplete_writer_without_replaying(repository, tmp_path, provider):
    from test_dispatch_boundaries import writer_setup
    request, ledger, store, manifest = writer_setup(repository, tmp_path)
    admission = request['admission']
    admission.update(assignment(admission['step'], admission['launch_id'], provider),
                     input_revision=manifest['input_revision'])
    calls = []
    native = native_transport({'complete': True}, calls)
    returned = dispatch.execute(request, run=native)
    assert returned['status'] == 'settled'
    assert returned['results'][0]['status'] == 'incomplete'
    assert ledger.status('run')['attempts']['design_author'] == 1
    assert all(item['state'] == 'released' for item in store.records('assignment'))
    replay = deepcopy(request)
    replay['evidence_dir'] = str(tmp_path / 'unlaunched-replay')
    with pytest.raises(ValueError, match='already admitted'):
        dispatch.execute(replay, run=native)
    assert len(calls) == 1
    assert not Path(replay['evidence_dir']).exists()


# The fixture creates a synthetic repository; no application or native provider is used.
from test_runtime_integration import repository  # noqa: E402,F401
