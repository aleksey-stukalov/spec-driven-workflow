"""Synthetic state-machine tests; never invoke providers."""
import copy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'plan_runtime.py'
sys.path.insert(0, str(TOOL.parent))
spec = importlib.util.spec_from_file_location('plan_runtime', TOOL)
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)


def context(**kwargs):
    return dict(verified_window=300000, capacity_source='synthetic client attestation', input_tokens=10000, tool_growth_tokens=1000, **kwargs)


def attest(step, plan='balanced', provider='codex'):
    route = pr.routes(plan)['steps'][step]['routes'][provider]
    return dict(source='offline fixture, not provider evidence', supported_models=[route['model']],
                supported_efforts={route['model']: [route['effort']]}, effective_model=route['model'], effective_effort=route['effort'])


def initialize(ledger, plan='balanced', run_id='r', **kwargs):
    return ledger.init(run_id=run_id, project='sample', change='26-11-09-901-synthetic-workflow',
                       slices=['a', 'b'], authority={'scope': 'synthetic harness only', 'approved_by': 'fixture'},
                       input_revision='bytes-a', context={}, plan=plan, applicable_steps=kwargs.get('applicable_steps', []),
                       spend_envelope=kwargs.get('spend_envelope', {'ceiling': None, 'currency': 'unknown', 'unknown_cost_policy': 'retain'}))


@pytest.fixture
def ledger(tmp_path):
    l = pr.Ledger(tmp_path / 'ledger.sqlite')
    initialize(l)
    return l


def payload(identity, step='lookup', plan='balanced', **kwargs):
    return dict(launch_id=identity, provider='codex', identity=identity, input_revision='bytes-a',
                attestation=attest(step, plan), context=context(), **kwargs)


def start(ledger, identity='worker', step='lookup', **kwargs):
    return ledger.start(run_id='r', step=step, **payload(identity, step, **kwargs))


def finish(ledger, launch_id, status='success', **result):
    if status == 'success':
        result = dict(complete=True, coverage_complete=True, truncated=False, findings=[],
                      input_revision=ledger.status('r')['launches'][launch_id]['input_revision']) | result
    return ledger.finish(run_id='r', launch_id=launch_id, status=status,
                         result=result, usage={'cost': None, 'input_tokens': 123, 'native_unknown': None})


def round_(ledger, rid, phase='I', plan='balanced'):
    return ledger.start_round(run_id='r', round_id=rid, phase=phase, input_revision='bytes-a',
                              reviewers=[payload(rid + '-a', pr.REVIEW_STEPS[phase][0], plan), payload(rid + '-b', pr.REVIEW_STEPS[phase][1], plan)])


def clean(ledger, rid, **override):
    result = dict(complete=True, coverage_complete=True, truncated=False, findings=[], input_revision='bytes-a')
    result.update(override)
    finish(ledger, rid + '-a', **result)
    finish(ledger, rid + '-b', **result)


def test_catalog_exact_matrix_and_strict_unknown(tmp_path):
    data = pr.load_catalog()
    assert len(data['steps']) == 15
    assert data['plans']['budget']['steps']['implementer']['routes']['codex'] == {'model': 'gpt-6-luna', 'effort': 'high'}
    assert data['plans']['smart']['steps']['implementation_fixer']['maximum'] == 2
    data['plans']['balanced']['steps']['lookup']['typo'] = 1
    p = tmp_path / 'bad.yaml'; p.write_text(yaml.safe_dump(data))
    with pytest.raises(pr.PlanError, match='unknown fields'): pr.load_catalog(p)
    p.write_text(pr.CATALOG.read_text() + '\ndefault: budget\n')
    with pytest.raises(pr.PlanError, match='duplicate'): pr.load_catalog(p)


@pytest.mark.parametrize('mutation', ['unknown_model', 'unknown_effort', 'override', 'native_option', 'actual_conflict'])
def test_fail_closed_capabilities(mutation):
    a = attest('lookup')
    if mutation == 'unknown_model': a['supported_models'] = []
    if mutation == 'unknown_effort': a['supported_efforts'] = {}
    if mutation == 'override': a['effective_effort'] = 'high'
    if mutation == 'native_option': a['native_options'] = {'max_output_tokens': 2000}
    if mutation == 'actual_conflict': a['actual_model'] = 'unknown'
    with pytest.raises(pr.PlanError): pr.preflight(step='lookup', provider='codex', attestation=a, context=context())


def test_unknown_actual_preserved():
    result = pr.preflight(step='lookup', provider='codex', attestation=attest('lookup'), context=context())
    assert result['actual'] == {'model': None, 'effort': None}
    assert result['requested']['model'] == 'gpt-6-luna'


def test_fit_reserves_growth_small_and_unknown_window():
    data = pr.load_catalog()
    result = pr.context_fit(data, 'standard', dict(context(), verified_window=100000), 'codex', 'gpt-6.1-sol')
    assert result['reserve_tokens'] == 32000 and result['input_target'] == 67000
    for bad in [dict(context(), verified_window=None), dict(context(), input_tokens=180001), dict(context(), tool_growth_tokens=300000)]:
        with pytest.raises(pr.PlanError): pr.context_fit(data, 'standard', bad, 'codex', 'gpt-6.1-sol')


def test_deep_and_pricing_reassessment():
    data = pr.load_catalog()
    c = dict(context(), input_tokens=255000, tool_growth_tokens=20000, profile='deep', verified_window=400000)
    with pytest.raises(pr.PlanError, match='deep context'): pr.context_fit(data, 'deep', c, 'codex', 'gpt-6-astra')
    with pytest.raises(pr.PlanError, match='pricing'): pr.context_fit(data, 'deep', c, 'codex', 'gpt-6-astra', {'deep_context': True})
    assert pr.context_fit(data, 'deep', dict(c, pricing_reassessed=True), 'codex', 'gpt-6-astra', {'deep_context': True})['pricing_reassessment']
    c = dict(context(), input_tokens=100001)
    with pytest.raises(pr.PlanError, match='pricing'): pr.context_fit(data, 'standard', c, 'claude', 'claude-haiku-5-5')


def test_failed_attempt_debited_duplicate_no_replay_resume(ledger):
    first = start(ledger)
    assert not first['replayed']
    assert start(ledger)['replayed']
    finish(ledger, 'worker', status='failed', error='synthetic')
    again = pr.Ledger(ledger.path)
    start(again, 'retry'); finish(again, 'retry', status='interrupted')
    with pytest.raises(pr.PlanError, match='allowance'): start(again, 'third')
    state = again.status('r')
    assert state['attempts']['lookup'] == 2 and len(state['usage']) == 2
    assert state['usage'][0]['record']['native_unknown'] is None


def test_duplicate_conflicts_rejected(ledger):
    start(ledger)
    with pytest.raises(pr.PlanError, match='conflicting duplicate'): start(ledger, estimated_cost=1)
    finish(ledger, 'worker', cost=1)
    with pytest.raises(pr.PlanError, match='conflicting finish'): finish(ledger, 'worker', cost=2)


def test_uncertain_launch_holds_slot_and_never_replays(ledger):
    start(ledger)
    finish(ledger, 'worker', status='uncertain')
    assert start(ledger)['replayed']
    initialize(ledger, run_id='other')
    ledger.start(run_id='other', step='lookup', **payload('other-worker'))
    with pytest.raises(pr.PlanError, match='slots'): start(ledger, 'third')


def test_atomic_two_slots_across_process_connections(ledger):
    initialize(ledger, run_id='other')
    initialize(ledger, run_id='third')
    def launch(item):
        run, identity = item
        try:
            return pr.Ledger(ledger.path).start(run_id=run, step='lookup', **payload(identity))['replayed']
        except pr.PlanError:
            return 'blocked'
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(launch, [('r', 'a'), ('other', 'b'), ('third', 'c')]))
    assert results.count(False) == 2 and results.count('blocked') == 1


def test_two_lenses_one_shared_round_and_final_bytes(ledger):
    r = round_(ledger, 'one')
    assert len(r['launches']) == 2 and len(ledger.status('r')['rounds']) == 1
    assert round_(ledger, 'one')['replayed']
    with pytest.raises(pr.PlanError, match='siblings'): start(ledger)
    clean(ledger, 'one')
    assert ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']
    ledger.switch(run_id='r', plan='balanced', input_revision='bytes-b', reason='material edit')
    assert not ledger.gate(run_id='r', phase='I', input_revision='bytes-b', checks_passed=True)['accepted']


@pytest.mark.parametrize('override', [{'truncated': True}, {'complete': False}, {'coverage_complete': False}, {'findings': [{'id': 'F1'}]}, {'input_revision': 'wrong'}])
def test_partial_or_findings_never_clean(ledger, override):
    round_(ledger, 'one'); clean(ledger, 'one', **override)
    assert not ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']


def test_failed_lens_new_round_both_fresh_and_charged(ledger):
    round_(ledger, 'one')
    finish(ledger, 'one-a', status='failed'); finish(ledger, 'one-b')
    state = ledger.status('r')
    assert state['rounds'][0]['status'] == 'incomplete'
    round_(ledger, 'two'); clean(ledger, 'two')
    assert len(ledger.status('r')['launches']) == 4
    assert ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']


def test_smart_two_consecutive_rounds_and_repair_reserve(tmp_path):
    l = pr.Ledger(tmp_path / 'smart.sqlite'); initialize(l, plan='smart')
    round_(l, 'one', plan='smart'); clean(l, 'one')
    assert not l.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']
    round_(l, 'two', plan='smart'); clean(l, 'two', findings=[{'id': 'F'}])
    round_(l, 'three', plan='smart'); clean(l, 'three')
    with pytest.raises(pr.PlanError, match='post-repair'): start(l, 'fix', step='implementation_fixer', plan='smart', owned_paths=['code.py'])
    round_(l, 'four', plan='smart'); clean(l, 'four')
    assert l.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']
    with pytest.raises(pr.PlanError, match='ceiling'): round_(l, 'five', plan='smart')


def test_slice_inventory_provider_plan_changes_never_reset(ledger):
    start(ledger, 'a', 'implementer', slice_id='a', owned_paths=['a.py']); finish(ledger, 'a')
    with pytest.raises(pr.PlanError, match='undeclared'): start(ledger, 'x', 'implementer', slice_id='invented', owned_paths=['x.py'])
    ledger.switch(run_id='r', plan='smart', input_revision='bytes-a', reason='approved route selection')
    state = ledger.status('r')
    assert state['attempts']['implementer:a'] == 1 and state['limits']['I'] == 3
    assert state['slices'] == ['a', 'b']


def test_nested_delegation_identity_ownership(ledger):
    with pytest.raises(pr.PlanError, match='nested'): start(ledger, parent_launch_id='parent')
    with pytest.raises(pr.PlanError, match='read-only'): start(ledger, owned_paths=['a.py'])
    start(ledger, 'writer', 'implementer', slice_id='a', owned_paths=['src'])
    with pytest.raises(pr.PlanError, match='overlapping'): start(ledger, 'writer2', 'implementer', slice_id='b', owned_paths=['src/a.py'])
    finish(ledger, 'writer')
    with pytest.raises(pr.PlanError, match='fresh'): ledger.start(run_id='r', step='lookup', **dict(payload('new'), identity='writer'))


def test_serious_dispute_requires_evidence_and_independent_acceptance(ledger):
    ledger.dispute(run_id='r', finding_id='F', severity='major', status='disputed', evidence='review and skeptic disagree')
    with pytest.raises(pr.PlanError, match='fresh independent'): ledger.dispute(run_id='r', finding_id='F', severity='major', status='resolved', evidence='skeptic says false')
    round_(ledger, 'fresh'); clean(ledger, 'fresh')
    assert 'serious_dispute' in ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['blockers']
    ledger.dispute(run_id='r', finding_id='F', severity='major', status='resolved', evidence='reproduction and independent pass', independent_round_id='fresh')
    assert ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']


def extension(l, **kwargs):
    return dict(receipt_id='approval-1', approved=True, approved_by='human fixture', reason='retry failed worker', evidence='retained failed result',
                used_allowed={'lookup': {'used': 2, 'allowed': 2}}, completed='two attempts', remaining='one lookup', additional={'lookup': 1},
                resulting_ceilings={'lookup': 3}, routes=l.status('r')['routes'], estimates={'usage': None, 'cost': None, 'time': None}, stopping_condition='one result then stop', **kwargs)


def test_extension_no_reply_denied_stale_or_duplicate(ledger):
    for i in range(2): start(ledger, str(i)); finish(ledger, str(i), status='failed')
    receipt = extension(ledger)
    with pytest.raises(pr.PlanError): ledger.extension(run_id='r', receipt=dict(receipt, approved=False))
    with pytest.raises(pr.PlanError): ledger.extension(run_id='r', receipt=dict(receipt, used_allowed={}))
    ledger.extension(run_id='r', receipt=receipt)
    ledger.extension(run_id='r', receipt=receipt)
    start(ledger, 'authorized')
    assert ledger.status('r')['limits']['lookup'] == 3
    with pytest.raises(pr.PlanError): ledger.extension(run_id='r', receipt=dict(receipt, reason='changed'))


def test_all_costs_failed_lead_tools_unknown_and_spend_envelope(tmp_path):
    l = pr.Ledger(tmp_path / 'cost.sqlite')
    initialize(l, spend_envelope={'ceiling': 5, 'currency': 'USD', 'unknown_cost_policy': 'block'})
    with pytest.raises(pr.PlanError, match='unknown cost'): start(l)
    with pytest.raises(pr.PlanError, match='premium'): start(l, estimated_cost=1, premium=True)
    start(l, estimated_cost=2)
    l.finish(run_id='r', launch_id='worker', status='failed', result={}, usage={'cost': 3, 'reasoning_tokens': None, 'tool_charge': .5})
    l.usage(run_id='r', receipt_id='lead', record={'cost': 2, 'source': 'native lead'})
    with pytest.raises(pr.PlanError, match='spend'): start(l, 'next', estimated_cost=.01)
    assert len(l.status('r')['usage']) == 2


def test_checkpoint_verifies_retained_bytes_and_ownership(ledger, tmp_path):
    source = tmp_path / 'source.py'; source.write_text('frozen')
    original = tmp_path / 'result.json'; original.write_text('{}')
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    record = dict(project='sample', change=ledger.status('r')['change'], task='bounded', worktree=str(tmp_path), base='base', head='head',
                  files={str(source): sha(source)}, original_results={str(original): sha(original)}, decisions=[], open_findings=[], checks=[], next_action='continue', ownership={'a': ['source.py']})
    ledger.checkpoint(run_id='r', checkpoint_id='cp', record=record)
    assert pr.Ledger(ledger.path).resume(run_id='r', checkpoint_id='cp', input_revision='bytes-a', ownership=record['ownership'])['resumed']
    with pytest.raises(pr.PlanError, match='ownership'): ledger.resume(run_id='r', checkpoint_id='cp', input_revision='bytes-a', ownership={})
    original.write_text('tampered')
    with pytest.raises(pr.PlanError, match='reference'): ledger.resume(run_id='r', checkpoint_id='cp', input_revision='bytes-a', ownership=record['ownership'])


def test_cli_json_routes_preflight_and_unknown_field():
    result = subprocess.run([sys.executable, str(TOOL), 'routes'], capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)['plan'] == 'balanced'
    request = dict(step='lookup', provider='codex', attestation=attest('lookup'), context=context(), typo=True)
    result = subprocess.run([sys.executable, str(TOOL), 'preflight'], input=json.dumps(request), capture_output=True, text=True)
    assert result.returncode == 2 and json.loads(result.stdout)['status'] == 'incomplete'


def test_writer_start_invalidates_old_final_byte_acceptance(ledger):
    round_(ledger, 'old'); clean(ledger, 'old')
    start(ledger, 'repair', 'implementation_fixer', owned_paths=['owned.py'])
    finish(ledger, 'repair', complete=True)
    assert not ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']
    round_(ledger, 'fresh'); clean(ledger, 'fresh')
    assert ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']


def test_serious_finding_auto_blocks_and_old_clean_cannot_resolve(ledger):
    round_(ledger, 'old'); clean(ledger, 'old')
    ledger.dispute(run_id='r', finding_id='F', severity='blocker', status='disputed', evidence='new defect')
    with pytest.raises(pr.PlanError, match='fresh independent'):
        ledger.dispute(run_id='r', finding_id='F', severity='blocker', status='resolved', evidence='old clean', independent_round_id='old')
    round_(ledger, 'bad'); clean(ledger, 'bad', findings=[{'id': 'G', 'severity': 'major', 'summary': 'unresolved'}])
    assert ledger.status('r')['disputes']['G']['status'] == 'disputed'


def test_declared_applicable_step_minima_and_each_slice(tmp_path):
    l = pr.Ledger(tmp_path / 'min.sqlite')
    initialize(l, applicable_steps=['context', 'implementer'])
    round_(l, 'review'); clean(l, 'review')
    gate = l.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)
    assert set(gate['blockers']) == {'missing_successful_step:context', 'missing_successful_step:implementer:a', 'missing_successful_step:implementer:b'}
    start(l, 'context-worker', 'context'); finish(l, 'context-worker', complete=True)
    for slice_id in ['a', 'b']:
        start(l, slice_id, 'implementer', slice_id=slice_id, owned_paths=[slice_id + '.py']); finish(l, slice_id, complete=True)
    round_(l, 'final'); clean(l, 'final')
    assert l.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']


def test_applicability_required():
    import inspect
    assert inspect.signature(pr.Ledger.init).parameters['applicable_steps'].default is inspect.Parameter.empty


def test_reconcile_binds_retained_phase_bytes_preserves_other_gate(ledger, tmp_path):
    round_(ledger, 'design', phase='D'); clean(ledger, 'design')
    source = tmp_path / 'bundle' / 'source'; source.mkdir(parents=True)
    (source / 'code.py').write_text('final implementation')
    inventory = {'code.py': hashlib.sha256((source / 'code.py').read_bytes()).hexdigest()}
    revision = pr.evidence.revision(inventory, {'code.py': '100644'}, {})
    manifest = dict(schema_version=3, kind='retained-review-source', project='sample', change=ledger.status('r')['change'], run_id='r', input_files=inventory, input_modes={'code.py': '100644'}, deleted_files={}, input_scope=['code.py'], input_revision=revision)
    path = source.parent / 'manifest.json'; path.write_text(json.dumps(manifest))
    refs = {'I': {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
    ledger.reconcile(run_id='r', input_revision=revision, phase_revisions={'I': revision}, reason='implementation changed; contracts identical', snapshot_references=refs)
    assert ledger.gate(run_id='r', phase='D', input_revision='bytes-a', checks_passed=True)['accepted']
    assert ledger.status('r')['phase_revisions']['I'] == revision
    reviewers = [dict(payload('new-a', 'implementation_behavior'), input_revision=revision), dict(payload('new-b', 'implementation_safety'), input_revision=revision)]
    ledger.start_round(run_id='r', round_id='implementation', phase='I', input_revision=revision, reviewers=reviewers)
    finish(ledger, 'new-a', complete=True, coverage_complete=True, truncated=False, findings=[], input_revision=revision)
    finish(ledger, 'new-b', complete=True, coverage_complete=True, truncated=False, findings=[], input_revision=revision)
    assert ledger.gate(run_id='r', phase='I', input_revision=revision, checks_passed=True)['accepted']
    (source / 'code.py').write_text('tampered')
    with pytest.raises(pr.PlanError, match='source changed'):
        ledger.reconcile(run_id='r', input_revision=revision, phase_revisions={'I': revision}, reason='invalid', snapshot_references=refs)


def test_reconcile_arbitrary_reference_cannot_authorize_phase(ledger, tmp_path):
    path = tmp_path / 'arbitrary.json'; path.write_text('{}')
    with pytest.raises(pr.PlanError, match='unsupported phase'):
        ledger.reconcile(run_id='r', input_revision='other', phase_revisions={'I': 'other'}, reason='fake', snapshot_references={'I': {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}})


def test_exact_slice_extension_cannot_multiply_capacity(ledger):
    start(ledger, 'a1', 'implementer', slice_id='a', owned_paths=['a.py']); finish(ledger, 'a1')
    start(ledger, 'a2', 'implementer', slice_id='a', owned_paths=['a.py']); finish(ledger, 'a2')
    receipt = extension(ledger)
    receipt.update(used_allowed={'implementer:a': {'used': 2, 'allowed': 2}}, additional={'implementer:a': 1}, resulting_ceilings={'implementer:a': 3})
    ledger.extension(run_id='r', receipt=receipt)
    state = ledger.status('r')
    assert state['limits']['implementer:a'] == 3 and state['limits']['implementer:b'] == 2
    start(ledger, 'a3', 'implementer', slice_id='a', owned_paths=['a.py'])


def test_context_override_conflicting_environment_is_blocked():
    a = attest('lookup')
    a['overrides'] = [{'source': 'environment', 'model': a['effective_model'], 'effort': 'xhigh'}]
    with pytest.raises(pr.PlanError, match='environment override'):
        pr.preflight(step='lookup', provider='codex', attestation=a, context=context())


def test_integration_edit_charges_repair_and_invalidates(ledger):
    round_(ledger, 'old'); clean(ledger, 'old')
    start(ledger, 'integration', 'lead_verify', owned_paths=['integrate.py'], material_edit=True)
    finish(ledger, 'integration', complete=True)
    state = ledger.status('r')
    assert state['attempts']['lead_verify'] == state['attempts']['implementation_fixer'] == 1
    assert not ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']


def test_smart_step_minima_cannot_weaken_two_round_minimum(tmp_path):
    l = pr.Ledger(tmp_path / 'min-smart.sqlite')
    initialize(l, plan='smart', applicable_steps=['context'])
    start(l, 'analyst', 'context', plan='smart'); finish(l, 'analyst', complete=True)
    round_(l, 'only-one', plan='smart'); clean(l, 'only-one')
    result = l.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)
    assert result['minimum'] == 2 and 'insufficient_clean_rounds' in result['blockers']


def test_adjudicator_requires_one_nonempty_deduplicated_findings_batch(ledger):
    with pytest.raises(pr.PlanError, match='nonempty'):
        start(ledger, 'skeptic', 'adjudicator', phase='I')
    with pytest.raises(pr.PlanError, match='deterministically'):
        start(ledger, 'skeptic', 'adjudicator', phase='I', findings=[{'id': 'F'}, {'id': 'F'}])
    start(ledger, 'skeptic', 'adjudicator', phase='I', findings=[{'id': 'F', 'severity': 'major'}])
    assert ledger.status('r')['attempts']['adjudicator:I'] == 1


def test_escalation_is_zero_until_named_human_receipt(ledger):
    escalation = dict(question='Why does recovery duplicate a writer?', approaches=['offline reproduction'], evidence=['F1'], allowed_files=[], maximum_calls=1, stopping_condition='one evidence-backed answer then stop')
    with pytest.raises(pr.PlanError, match='allowance'):
        start(ledger, 'expert', 'escalation', escalation=escalation)
    receipt = extension(ledger)
    receipt.update(used_allowed={'escalation': {'used': 0, 'allowed': 0}}, additional={'escalation': 1}, resulting_ceilings={'escalation': 1}, escalation=escalation)
    ledger.extension(run_id='r', receipt=receipt)
    with pytest.raises(pr.PlanError, match='matching human'):
        start(ledger, 'expert', 'escalation', escalation=dict(escalation, question='Unapproved different scope'))
    start(ledger, 'expert', 'escalation', escalation=escalation)


def recovery_request(ledger, tmp_path, launch_id='worker', status='success', result=None, usage=None, usage_complete=True, receipt_id='recover-1'):
    def save(name, value):
        path = tmp_path / (receipt_id + '-' + name + '.json')
        path.write_text(json.dumps(value))
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    result_ref = save('original-result', result if result is not None else {
        'complete': True, 'coverage_complete': True, 'truncated': False, 'findings': [], 'input_revision': 'bytes-a'})
    usage_ref = save('usage', usage if usage is not None else {'cost': 2, 'input_tokens': None, 'future_native_field': 'retained'})
    process = dict(run_id='r', launch_id=launch_id, input_revision='bytes-a', process_stopped=True, status=status,
                   source='retained process exit and original return reconciliation', original_result_sha256=result_ref['sha256'], usage_sha256=usage_ref['sha256'])
    process_ref = save('process', process)
    return dict(run_id='r', launch_id=launch_id, receipt_id=receipt_id, status=status, original_result=result_ref,
                process_evidence=process_ref, usage_reference=usage_ref, usage_complete=usage_complete,
                authority={'scope': ledger.status('r')['authority']['scope'], 'approved_by': 'fixture human', 'source': 'explicit recovery instruction'})


def test_uncertain_writer_partial_original_return_preserves_counter_and_usage(ledger, tmp_path):
    start(ledger, 'worker', 'implementer', slice_id='a', owned_paths=['a.py'])
    finish(ledger, 'worker', status='uncertain', outcome='unknown')
    request = recovery_request(ledger, tmp_path, result={'complete': False, 'input_revision': 'bytes-a', 'changed_files': ['a.py'], 'unresolved': ['writer stopped before checks']}, usage={'cost': None, 'partial_native': 12}, usage_complete=False)
    recovered = ledger.recover_launch(**request)
    assert recovered['launch']['status'] == 'incomplete' and recovered['launch']['result']['complete'] is False
    state = ledger.status('r')
    assert state['attempts']['implementer:a'] == 1 and len(state['launches']) == 1
    assert state['recoveries']['recover-1']['prior_launch']['status'] == 'uncertain'
    assert state['recoveries']['recover-1']['prior_launch']['result']['outcome'] == 'unknown'
    assert len(state['usage']) == 2 and state['accounting']['total_cost'] is None
    assert state['usage'][1]['record']['partial_native'] == 12
    assert not ledger._active(state)
    assert ledger.start(run_id='r', step='implementer', **payload('worker', 'implementer', slice_id='a', owned_paths=['a.py']))['replayed']


def test_recovery_known_failure_frees_slot_without_forging_success(ledger, tmp_path):
    start(ledger)
    finish(ledger, 'worker', status='uncertain')
    request = recovery_request(ledger, tmp_path, status='failed', result={'complete': False, 'native_exit_code': 1})
    recovered = ledger.apply('recover-launch', request)
    assert recovered['launch']['status'] == 'failed' and recovered['launch']['result']['native_exit_code'] == 1
    assert ledger.status('r')['attempts']['lookup'] == 1
    start(ledger, 'new-worker')
    assert ledger.status('r')['attempts']['lookup'] == 2


@pytest.mark.parametrize('bad', ['missing_original', 'tampered_original', 'stale_original', 'stale_process', 'process_live', 'wrong_authority', 'mismatched_original_hash'])
def test_recovery_requires_current_bound_originals_and_stopped_process(ledger, tmp_path, bad):
    start(ledger); finish(ledger, 'worker', status='uncertain')
    request = recovery_request(ledger, tmp_path)
    if bad == 'missing_original': Path(request['original_result']['path']).unlink()
    if bad == 'tampered_original': Path(request['original_result']['path']).write_text('{"complete":true}')
    if bad == 'wrong_authority': request['authority']['scope'] = 'unrelated task'
    if bad in {'stale_original', 'stale_process', 'process_live', 'mismatched_original_hash'}:
        ref = request['original_result'] if bad == 'stale_original' else request['process_evidence']
        path = Path(ref['path']); data = json.loads(path.read_text())
        if bad in {'stale_original', 'stale_process'}: data['input_revision'] = 'wrong bytes'
        if bad == 'process_live': data['process_stopped'] = False
        if bad == 'mismatched_original_hash': data['original_result_sha256'] = 'wrong'
        path.write_text(json.dumps(data)); ref['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        if bad == 'stale_original':
            process_ref = request['process_evidence']; process_path = Path(process_ref['path'])
            observed = json.loads(process_path.read_text()); observed['original_result_sha256'] = ref['sha256']
            process_path.write_text(json.dumps(observed)); process_ref['sha256'] = hashlib.sha256(process_path.read_bytes()).hexdigest()
    with pytest.raises(pr.PlanError): ledger.recover_launch(**request)
    state = ledger.status('r')
    assert state['launches']['worker']['status'] == 'uncertain' and len(state['usage']) == 1
    assert state['attempts']['lookup'] == 1 and not state.get('recoveries')


def test_recovery_receipt_idempotent_conflicting_duplicate_blocked(ledger, tmp_path):
    start(ledger); finish(ledger, 'worker', status='uncertain')
    request = recovery_request(ledger, tmp_path)
    assert not ledger.recover_launch(**request)['replayed']
    assert pr.Ledger(ledger.path).recover_launch(**request)['replayed']
    state = ledger.status('r')
    assert len(state['usage']) == 2 and state['accounting']['total_cost'] == 2
    assert state['usage'][0]['record']['cost'] is None and state['usage'][0]['superseded_by'] == 'recovery:recover-1'
    assert state['accounting']['unknown_cost_records'] == 0
    altered = copy.deepcopy(request); altered['authority']['source'] = 'different approval source'
    with pytest.raises(pr.PlanError, match='conflicting recovery'): ledger.recover_launch(**altered)
    assert len(ledger.status('r')['usage']) == 2


def test_true_review_recovery_completes_existing_round_without_new_lenses(ledger, tmp_path):
    round_(ledger, 'lost')
    result = dict(complete=True, coverage_complete=True, truncated=False, findings=[], input_revision='bytes-a')
    finish(ledger, 'lost-a', status='uncertain'); finish(ledger, 'lost-b', **result)
    assert not ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']
    request = recovery_request(ledger, tmp_path, launch_id='lost-a', result=result)
    ledger.recover_launch(**request)
    state = ledger.status('r')
    assert state['rounds'][0]['status'] == 'complete' and state['rounds'][0]['clean']
    assert len(state['rounds']) == 1 and len(state['launches']) == 2
    assert state['launches']['lost-a']['identity'] == 'lost-a' and state['launches']['lost-a']['input_revision'] == 'bytes-a'
    assert ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']


def test_recovered_review_partial_result_never_cleans_round(ledger, tmp_path):
    round_(ledger, 'partial')
    finish(ledger, 'partial-a', status='uncertain'); finish(ledger, 'partial-b', complete=True, coverage_complete=True, truncated=False, findings=[], input_revision='bytes-a')
    request = recovery_request(ledger, tmp_path, launch_id='partial-a', result={'complete': True, 'coverage_complete': False, 'truncated': True, 'findings': [], 'input_revision': 'bytes-a'})
    ledger.recover_launch(**request)
    assert not ledger.status('r')['rounds'][0]['clean']
    assert not ledger.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)['accepted']


def test_recovery_cumulative_usage_does_not_double_count_or_hide_known_cost(ledger, tmp_path):
    start(ledger)
    ledger.finish(run_id='r', launch_id='worker', status='uncertain', result={}, usage={'cost': 3, 'native_partial': 'original'})
    request = recovery_request(ledger, tmp_path, usage={'cost': 5, 'native_cumulative': 'final'})
    ledger.recover_launch(**request)
    state = ledger.status('r')
    assert len(state['usage']) == 2 and state['accounting']['known_cost'] == state['accounting']['total_cost'] == 5
    assert state['usage'][0]['record']['cost'] == 3
    # Replaying the original usage receipt remains idempotent after supersession.
    ledger.usage(run_id='r', receipt_id='launch:worker', launch_id='worker', record={'cost': 3, 'native_partial': 'original'})
    assert ledger.status('r')['accounting']['known_cost'] == 5


def test_recovery_unknown_final_billing_retains_known_prior_subtotal(ledger, tmp_path):
    start(ledger)
    ledger.finish(run_id='r', launch_id='worker', status='uncertain', result={}, usage={'cost': 3})
    request = recovery_request(ledger, tmp_path, usage={'cost': None}, usage_complete=True)
    ledger.recover_launch(**request)
    state = ledger.status('r')
    assert state['accounting']['known_cost'] == 3 and state['accounting']['total_cost'] is None
    assert state['accounting']['unknown_cost_records'] == 1


def test_recovery_lower_final_bill_cannot_erase_known_charge(ledger, tmp_path):
    start(ledger)
    ledger.finish(run_id='r', launch_id='worker', status='uncertain', result={}, usage={'cost': 3})
    request = recovery_request(ledger, tmp_path, usage={'cost': 1})
    with pytest.raises(pr.PlanError, match='hide previously known'): ledger.recover_launch(**request)
    state = ledger.status('r')
    assert state['launches']['worker']['status'] == 'uncertain' and len(state['usage']) == 1


def test_recovery_cli_settles_without_launch_and_same_receipt_replays(ledger, tmp_path):
    start(ledger); finish(ledger, 'worker', status='uncertain')
    request = recovery_request(ledger, tmp_path, status='interrupted', result={'complete': False, 'input_revision': 'bytes-a', 'stop_reason': 'operator reconciled stopped process'})
    for expected in [False, True]:
        completed = subprocess.run([sys.executable, str(TOOL), '--db', ledger.path, 'recover-launch'], input=json.dumps(request), capture_output=True, text=True)
        assert completed.returncode == 0
        assert json.loads(completed.stdout)['replayed'] is expected
    assert ledger.status('r')['attempts']['lookup'] == 1
    assert ledger.status('r')['launches']['worker']['status'] == 'interrupted'


def test_recovery_after_missing_finish_can_resolve_charged_started_assignment(ledger, tmp_path):
    start(ledger)
    request = recovery_request(ledger, tmp_path, status='failed', result={'complete': False, 'error_type': 'worker_terminated'})
    ledger.recover_launch(**request)
    state = ledger.status('r')
    assert state['recoveries']['recover-1']['prior_launch']['status'] == 'started'
    assert state['attempts']['lookup'] == 1 and len(state['usage']) == 1


def test_recovered_partial_writer_does_not_satisfy_declared_step_minimum(tmp_path):
    l = pr.Ledger(tmp_path / 'partial-writer.sqlite'); initialize(l, applicable_steps=['implementer'])
    start(l, 'worker', 'implementer', slice_id='a', owned_paths=['a.py']); finish(l, 'worker', status='uncertain')
    l.recover_launch(**recovery_request(l, tmp_path, result={'complete': False, 'input_revision': 'bytes-a', 'remaining': ['checks not completed']}))
    start(l, 'slice-b', 'implementer', slice_id='b', owned_paths=['b.py']); finish(l, 'slice-b', complete=True)
    round_(l, 'review'); clean(l, 'review')
    gate = l.gate(run_id='r', phase='I', input_revision='bytes-a', checks_passed=True)
    assert not gate['accepted'] and 'missing_successful_step:implementer:a' in gate['blockers']


def test_reconciled_cumulative_usage_controls_spend_without_duplicate_or_unknown_charge(tmp_path):
    l = pr.Ledger(tmp_path / 'recovered-spend.sqlite')
    initialize(l, spend_envelope={'ceiling': 5, 'currency': 'USD', 'unknown_cost_policy': 'block'})
    start(l, estimated_cost=1); finish(l, 'worker', status='uncertain')
    with pytest.raises(pr.PlanError, match='unknown cost'): start(l, 'blocked', estimated_cost=1)
    l.recover_launch(**recovery_request(l, tmp_path, usage={'cost': 2}, usage_complete=True))
    start(l, 'within-envelope', estimated_cost=3)
    assert l.status('r')['accounting']['total_cost'] == 2


def test_new_plan_reconcile_cannot_promote_legacy_hash_only_source(ledger, tmp_path):
    source = tmp_path / 'legacy' / 'source'; source.mkdir(parents=True)
    (source / 'code.py').write_text('legacy bytes')
    files = {'code.py': hashlib.sha256((source / 'code.py').read_bytes()).hexdigest()}
    revision = pr.digest(files)
    manifest = dict(schema_version=2, kind='retained-review-source', project='sample', change=ledger.status('r')['change'], run_id='r', input_files=files, input_scope=['code.py'], input_revision=revision)
    path = source.parent / 'manifest.json'; path.write_text(json.dumps(manifest))
    assert pr.evidence.verify(path.parent)['schema_version'] == 2
    with pytest.raises(pr.PlanError, match='schema 3'):
        ledger.reconcile(run_id='r', input_revision=revision, phase_revisions={'I': revision}, reason='cannot promote legacy evidence', snapshot_references={'I': {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}})
    assert ledger.status('r')['input_revision'] == 'bytes-a'
