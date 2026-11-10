"""Final handoff rejects stale source, missing originals and incomplete lifecycle."""
import hashlib
import json
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import evidence
import lifecycle
import plan_runtime
from test_runtime_integration import repository, git, reference, CHANGE
from test_portable_evidence import use_companion


def accepted_fixture(repository, tmp_path, *, omission=None, project_root='project', skip_specs=False, invalid=None, config_name='config.yaml', companion=False):
    root = repository
    spec_home = Path(project_root) / 'openspec'
    if project_root == '.':
        (root / 'project/openspec').rename(root / 'openspec')
        registration = root / 'agentic_harness/projects.yaml'
        data = yaml.safe_load(registration.read_text())
        data['projects']['synthetic'].update(root='.', queue='openspec/queue.yaml', code_roots=['.'])
        registration.write_text(yaml.safe_dump(data))
    if config_name != 'config.yaml':
        (root / spec_home / 'config.yaml').rename(root / spec_home / config_name)
    if companion:
        use_companion(root)
    active = root / spec_home / 'changes' / CHANGE
    contract = '### Requirement: Preserve exact sources\nSHALL retain bytes.\n\n#### Scenario: stable-source\n- **WHEN** captured\n- **THEN** retained\n'
    if skip_specs:
        (active / '.openspec.yaml').write_text('schema: spec-driven\nskip_specs: true\n')
        (active / 'specs/synthetic/spec.md').unlink()
        baseline = root / spec_home / 'specs/existing/spec.md'
        baseline.parent.mkdir(parents=True)
        baseline.write_text(contract)
    if skip_specs or project_root == '.' or config_name != 'config.yaml' or companion:
        git(root, 'add', '.')
        git(root, 'commit', '-m', 'Synthetic project registration and existing behavior')
    archive = active.parent / 'archive' / ('2026-11-09-' + CHANGE)
    archive.parent.mkdir()
    active.rename(archive)
    (archive / 'tasks.md').write_text('- [x] Verified implementation\n')
    if not skip_specs or invalid == 'contradictory-delta':
        (archive / 'specs/synthetic/spec.md').write_text('## ADDED Requirements\n\n' + contract)
        main_spec = root / spec_home / 'specs/synthetic/spec.md'
        main_spec.parent.mkdir(parents=True)
        main_spec.write_text(contract)
    if invalid == 'modified-baseline':
        baseline.write_text(contract.replace('retain bytes', 'discard bytes'))
    elif invalid == 'deleted-baseline':
        baseline.unlink()
    elif invalid == 'missing-declaration':
        (archive / '.openspec.yaml').unlink()
    elif invalid == 'nonboolean-declaration':
        (archive / '.openspec.yaml').write_text('skip_specs: "true"\n')
    elif invalid == 'unchecked-tasks':
        (archive / 'tasks.md').write_text('- [ ] Verification still pending\n')
    (root / 'source.py').write_text('value = (1)\n' if skip_specs else 'value = 2\n')
    head = git(root, 'rev-parse', 'HEAD')
    design_path, implementation_path = tmp_path / 'design', tmp_path / 'implementation'
    contract_path = (archive / ('.openspec.yaml' if skip_specs else 'specs/synthetic/spec.md')).relative_to(root).as_posix()
    design_scope = sorted(['contract.md', *((archive / name).relative_to(root).as_posix() for name in ('proposal.md', 'design.md')),
                          *([contract_path] if (root / contract_path).is_file() else [])])
    if omission == 'design-contract': design_scope.remove(contract_path)
    design = evidence.materialize(root, design_path, design_scope, project='synthetic', change=CHANGE, run_id='r', base=head, policy='plans-v1')
    changed = evidence.changed_scope(root, head)
    scope = sorted(set(changed['input_scope']) | {'source.py', 'contract.md', 'agentic_harness/projects.yaml',
                                                (spec_home / 'queue.yaml').as_posix(), (spec_home / config_name).as_posix()}
                   | ({(spec_home / 'workflow.yaml').as_posix()} if companion else set()))
    omitted = {'archive':contract_path, 'registry':'agentic_harness/projects.yaml', 'changed-code':'source.py',
               'workflow-config': (spec_home / 'workflow.yaml').as_posix()}.get(omission)
    if omitted: scope.remove(omitted)
    deleted = [] if omission == 'deleted' else changed['deleted_scope']
    implementation = evidence.materialize(root, implementation_path, scope, deleted_scope=deleted, project='synthetic', change=CHANGE, run_id='r', base=head, policy='plans-v1')
    ledger_path = tmp_path / 'ledger.sqlite'
    ledger = plan_runtime.Ledger(ledger_path)
    ledger.init(run_id='r', project='synthetic', change=CHANGE, plan='balanced', slices=['existing'], authority={'scope':'synthetic', 'approved_by':'fixture'},
        input_revision=implementation['input_revision'], context={}, applicable_steps=[], spend_envelope={'ceiling':None,'currency':'unknown','unknown_cost_policy':'retain'})
    design_manifest = design_path / 'manifest.json'
    ledger.reconcile(run_id='r', input_revision=implementation['input_revision'], phase_revisions={'D':design['input_revision']}, reason='Retained design scope unchanged',
        snapshot_references={'D':{'path':str(design_manifest),'sha256':hashlib.sha256(design_manifest.read_bytes()).hexdigest()}})
    originals = {}
    for phase, manifest in [('D', design), ('I', implementation)]:
        reviewers = []
        for n, step in enumerate(plan_runtime.REVIEW_STEPS[phase]):
            route = plan_runtime.routes()['steps'][step]['routes']['codex']
            reviewers.append(dict(launch_id=phase+str(n), identity=phase+str(n), provider='codex', input_revision=manifest['input_revision'],
                attestation={'source':'synthetic evidence','supported_models':[route['model']],'supported_efforts':{route['model']:[route['effort']]},'effective_model':route['model'],'effective_effort':route['effort']},
                context={'verified_window':300000,'capacity_source':'synthetic','input_tokens':10000,'tool_growth_tokens':1000}))
        started = ledger.start_round(run_id='r', round_id=phase, phase=phase, input_revision=manifest['input_revision'], reviewers=reviewers)
        for launch in started['launches']:
            ident = launch['launch_id']; folder = tmp_path / ('original-' + ident); folder.mkdir()
            result = dict(complete=True,coverage_complete=True,truncated=False,findings=[],input_revision=manifest['input_revision'])
            refs = {'result':reference(folder/'result.json',result), 'invocation':reference(folder/'invocation.json',{'launch':launch})}
            for name, text in [('prompt','Review the full assigned source.'),('stdout',json.dumps(result)),('stderr','')]:
                path=folder/(name+'.txt');path.write_text(text);refs[name]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            originals[ident] = refs
            ledger.finish(run_id='r',launch_id=ident,status='success',result=result,usage={'cost':None})
    check = reference(tmp_path/'checks.json',{'command':['true'],'exit_code':0,'head':head,'input_revision':implementation['input_revision']})
    request=dict(worktree=str(root),bundle=str(implementation_path),design_bundle=str(design_path),ledger=str(ledger_path),project='synthetic',change=CHANGE,checks=[check],originals=originals)
    return root, archive, request, head, implementation, check, originals


@pytest.mark.parametrize('omission', [None, 'archive', 'registry', 'changed-code', 'deleted', 'design-contract'])
def test_final_gate_binds_both_scopes_originals_checks_and_same_pr_lifecycle(repository, tmp_path, omission):
    root, archive, request, head, implementation, check, originals = accepted_fixture(repository, tmp_path, omission=omission)
    if omission:
        with pytest.raises(ValueError, match='scope omits|acceptance omits'):
            lifecycle.acceptance_gate(request)
        return
    assert lifecycle.acceptance_gate(request)['status']=='verified'
    archive_spec = archive / 'specs/synthetic/spec.md'
    original_spec = archive_spec.read_text()
    archive_spec.write_text(original_spec.replace('SHALL retain bytes.', 'SHALL discard bytes.'))
    with pytest.raises(ValueError, match='current final bytes'): lifecycle.acceptance_gate(request)
    archive_spec.write_text(original_spec)
    # A caller cannot turn a missing original into a clean ledger-only assertion.
    wrong=dict(request,originals={k:v for k,v in originals.items() if k!='I0'})
    with pytest.raises(ValueError,match='original evidence missing'):lifecycle.acceptance_gate(wrong)
    check_path=Path(check['path']);check_path.write_text('{}')
    with pytest.raises(ValueError,match='hash mismatch'):lifecycle.acceptance_gate(request)
    request['checks']=[reference(check_path,{'command':['false'],'exit_code':0,'head':head,'input_revision':implementation['input_revision']})]
    with pytest.raises(ValueError,match='required checks missing'):lifecycle.acceptance_gate(request)
    request['checks']=[reference(check_path,{'command':['true'],'exit_code':0,'head':head,'input_revision':implementation['input_revision']})]
    (root/'source.py').write_text('changed after accepted review\n')
    with pytest.raises(ValueError,match='current final bytes'):lifecycle.acceptance_gate(request)


def test_sync_compares_full_bodies_and_removed_renamed_semantics():
    block = '### Requirement: Keep source\nSHALL retain bytes.\n\n#### Scenario: stable\n- **WHEN** saved\n- **THEN** retained\n'
    lifecycle.synchronized_delta('## ADDED Requirements\n\n'+block, block)
    with pytest.raises(ValueError, match='complete requirement bodies'):
        lifecycle.synchronized_delta('## ADDED Requirements\n\n'+block, block.replace('retain bytes', 'discard bytes'))
    with pytest.raises(ValueError, match='complete requirement bodies'):
        lifecycle.synchronized_delta('## MODIFIED Requirements\n\n'+block, block.replace('**THEN** retained', '**THEN** destroyed'))
    with pytest.raises(ValueError, match='removed requirement'):
        lifecycle.synchronized_delta('## REMOVED Requirements\n\n'+block, block)
    lifecycle.synchronized_delta('## REMOVED Requirements\n\n'+block, '')
    rename = '## RENAMED Requirements\n- FROM: `### Requirement: Keep source`\n- TO: `### Requirement: Retain source`\n'
    with pytest.raises(ValueError, match='renamed requirement'):
        lifecycle.synchronized_delta(rename, block)
    lifecycle.synchronized_delta(rename, block.replace('Requirement: Keep source', 'Requirement: Retain source'))
    fenced = block + '\n```md\n## Example heading\nSHALL retain bytes inside the example.\n```\n'
    with pytest.raises(ValueError, match='complete requirement bodies'):
        lifecycle.synchronized_delta('## ADDED Requirements\n\n'+fenced, fenced.replace('inside the example', 'outside the example'))


@pytest.mark.parametrize('project_root', ['.', 'project'])
@pytest.mark.parametrize('skip_specs', [False, True])
@pytest.mark.parametrize('config_name', ['config.yaml', 'config.yml'])
def test_root_and_component_projects_complete_explicit_spec_lifecycles(repository, tmp_path, project_root, skip_specs, config_name):
    _, _, request, *_ = accepted_fixture(repository, tmp_path, project_root=project_root, skip_specs=skip_specs, config_name=config_name)
    verdict = lifecycle.acceptance_gate(request)
    assert verdict['status'] == 'verified'
    assert verdict['specification_mode'] == ('unchanged' if skip_specs else 'synchronized')


@pytest.mark.parametrize('invalid,diagnostic', [
    ('contradictory-delta', 'contradicts archived capability'),
    ('modified-baseline', 'leave implemented capability specifications unchanged'),
    ('deleted-baseline', 'leave implemented capability specifications unchanged'),
    ('missing-declaration', 'capability evidence is missing'),
    ('nonboolean-declaration', 'boolean skip_specs'),
    ('unchecked-tasks', 'unverified lifecycle tasks'),
])
def test_no_behavior_change_cannot_fake_specification_completion(repository, tmp_path, invalid, diagnostic):
    _, _, request, *_ = accepted_fixture(repository, tmp_path, project_root='.', skip_specs=True, invalid=invalid)
    with pytest.raises(ValueError, match=diagnostic):
        lifecycle.acceptance_gate(request)


@pytest.mark.parametrize('omission', ['archive', 'registry', 'changed-code', 'deleted', 'design-contract'])
def test_no_behavior_change_retains_final_review_and_metadata_binding(repository, tmp_path, omission):
    _, _, request, *_ = accepted_fixture(repository, tmp_path, project_root='.', skip_specs=True, omission=omission)
    with pytest.raises(ValueError, match='scope omits|acceptance omits'):
        lifecycle.acceptance_gate(request)


@pytest.mark.parametrize('project_root', ['.', 'project'])
@pytest.mark.parametrize('skip_specs', [False, True])
@pytest.mark.parametrize('omission', [None, 'workflow-config'])
def test_final_review_requires_unchanged_companion_check_authority(repository, tmp_path, project_root, skip_specs, omission):
    root, _, request, head, *_ = accepted_fixture(
        repository, tmp_path, project_root=project_root, skip_specs=skip_specs,
        companion=True, omission=omission,
    )
    companion = (Path(project_root) / 'openspec/workflow.yaml').as_posix()
    assert companion not in evidence.changed_scope(root, head)['input_scope']
    if omission:
        with pytest.raises(ValueError, match='scope omits.*check authority'):
            lifecycle.acceptance_gate(request)
    else:
        assert lifecycle.acceptance_gate(request)['status'] == 'verified'


def test_remote_operation_marker_is_workflow_specific():
    assert lifecycle.GhRemote.marker({'id': 'operation-1', 'hash': 'abc'}) == '<!-- sdw-operation:operation-1:abc -->'
