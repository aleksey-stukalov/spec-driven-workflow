"""Real dispatcher artifacts must satisfy final acceptance and deletion review."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_runtime_integration import repository, setup_dispatch, reference, git, CHANGE
import evidence
import coordination
import dispatch
import lifecycle


def test_real_dispatch_originals_pass_final_lifecycle_acceptance(repository, tmp_path):
    scratch, repo = tmp_path, repository
    request,ledger,store,initial=setup_dispatch(repo,scratch)
    root=Path(request['worktree']); store.thaw(root,'fixture')
    active=root/'project/openspec/changes'/CHANGE
    archive=active.parent/'archive'/('2026-11-09-'+CHANGE);archive.parent.mkdir();active.rename(archive)
    (archive/'tasks.md').write_text('- [x] Verified implementation\n')
    block='### Requirement: Preserve exact sources\nSHALL retain bytes.\n\n#### Scenario: stable-source\n- **WHEN** captured\n- **THEN** retained\n'
    (archive/'specs/synthetic/spec.md').write_text('## ADDED Requirements\n\n'+block)
    main=root/'project/openspec/specs/synthetic/spec.md';main.parent.mkdir(parents=True);main.write_text(block)
    base=git(root,'rev-parse','HEAD');changed=evidence.changed_scope(root,base)
    scope=sorted(set(changed['input_scope'])|{'source.py','contract.md','agentic_harness/projects.yaml','project/openspec/queue.yaml','project/openspec/config.yaml'})
    bundle=scratch/'final-source'
    manifest=evidence.materialize(root,bundle,scope,deleted_scope=changed['deleted_scope'],project='synthetic',change=CHANGE,run_id='run',base=base,policy='plans-v1')
    mref={'path':str(bundle/'manifest.json'),'sha256':hashlib.sha256((bundle/'manifest.json').read_bytes()).hexdigest()}
    ledger.reconcile(run_id='run',input_revision=manifest['input_revision'],phase_revisions={'D':manifest['input_revision'],'I':manifest['input_revision']},reason='Synthetic final lifecycle',snapshot_references={'D':mref,'I':mref})
    intake=json.loads(Path(request['intake']['path']).read_text());intake['scope']=scope;intake['authorities'][0]['scope']=scope
    request['intake']=reference(scratch/'final-intake.json',intake)
    store.freeze(root,coordination.source_state(root)['content_revision'],'fixture')
    result=dict(complete=True,coverage_complete=True,truncated=False,findings=[],input_revision=manifest['input_revision'])
    def provider(argv,**kwargs):
     if argv[0]=='codex':
      Path(argv[argv.index('--output-last-message')+1]).write_text(json.dumps(result));return SimpleNamespace(returncode=0,stdout='{}\n',stderr='')
     return SimpleNamespace(returncode=0,stdout=json.dumps({'structured_output':result,'total_cost_usd':0.01}),stderr='')
    originals={}
    for phase in ('D','I'):
     req=copy.deepcopy(request);dest=scratch/(phase+'-results');req.update(bundle=str(bundle),evidence_dir=str(dest));req['admission'].update(phase=phase,round_id=phase+'-1',input_revision=manifest['input_revision'])
     for n,reviewer in enumerate(req['admission']['reviewers']):reviewer.update(launch_id=phase+str(n),identity=phase+str(n),input_revision=manifest['input_revision'])
     outcome=dispatch.execute(req,run=provider);assert outcome['status']=='settled'
     for reviewer in req['admission']['reviewers']:
      ident=reviewer['launch_id'];folder=dest/ident
      originals[ident]={kind:{'path':str(folder/name),'sha256':hashlib.sha256((folder/name).read_bytes()).hexdigest()} for kind,name in [('prompt','prompt.txt'),('result','original-result.json'),('invocation','invocation.json'),('stdout','stdout.txt'),('stderr','stderr.txt')]}
    check=reference(scratch/'checks.json',{'command':['true'],'exit_code':0,'head':manifest['input_head'],'input_revision':manifest['input_revision']})
    gate=dict(worktree=str(root),bundle=str(bundle),design_bundle=str(bundle),ledger=request['ledger'],project='synthetic',change=CHANGE,checks=[check],originals=originals)
    for phase in ('D','I'):assert ledger.gate(run_id='run',phase=phase,input_revision=manifest['input_revision'],checks_passed=True)['accepted']
    assert lifecycle.acceptance_gate(gate)['status'] == 'verified'
    invocation_path = Path(originals['D0']['invocation']['path'])
    invocation = json.loads(invocation_path.read_text())
    assert invocation['launch']['effective'] == ledger.status('run')['launches']['D0']['effective']
    assert (invocation_path.parent / 'prepared-invocation.json').is_file()
    # A missing admitted field is a controlled evidence rejection, not KeyError.
    invocation['launch'].pop('effective')
    originals['D0']['invocation'] = reference(invocation_path, invocation)
    with pytest.raises(ValueError, match='original invocation differs'):
        lifecycle.acceptance_gate(gate)


def test_deletion_only_review_reserves_and_exposes_deleted_originals(repository, tmp_path):
    request, ledger, store, initial = setup_dispatch(repository, tmp_path)
    root = Path(request['worktree'])
    store.thaw(root, 'fixture')
    original = (root / 'source.py').read_bytes()
    (root / 'source.py').unlink()
    bundle = tmp_path / 'deletion-source'
    manifest = evidence.materialize(root, bundle, [], deleted_scope=['source.py'],
        project='synthetic', change=CHANGE, run_id='run', base=initial['base_commit'], policy='plans-v1')
    manifest_path = bundle / 'manifest.json'
    ledger.reconcile(run_id='run', input_revision=manifest['input_revision'], phase_revisions={'I':manifest['input_revision']},
        reason='Review a deletion-only slice', snapshot_references={'I':{'path':str(manifest_path), 'sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest()}})
    store.freeze(root, coordination.source_state(root)['content_revision'], 'fixture')
    request.update(bundle=str(bundle), evidence_dir=str(tmp_path / 'deleted-results'))
    request['admission']['input_revision'] = manifest['input_revision']
    for reviewer in request['admission']['reviewers']:
        reviewer['input_revision'] = manifest['input_revision']
    calls = []
    def provider(argv, **kwargs):
        calls.append(argv[0])
        assert not list(Path(kwargs['cwd']).iterdir())
        assert (bundle / 'deleted-source/source.py').read_bytes() == original
        assert 'deleted-source' in kwargs['input'] and '"deleted_paths": ["source.py"]' in kwargs['input']
        result = dict(complete=True, coverage_complete=True, truncated=False, findings=[], input_revision=manifest['input_revision'])
        if argv[0] == 'codex':
            Path(argv[argv.index('--output-last-message') + 1]).write_text(json.dumps(result))
            return SimpleNamespace(returncode=0, stdout='{}\n', stderr='')
        return SimpleNamespace(returncode=0, stdout=json.dumps({'structured_output':result, 'total_cost_usd':0.01}), stderr='')
    assert dispatch.execute(request, run=provider)['status'] == 'settled'
    assert len(calls) == 2
    assert all(a['files'] == [str(root / 'source.py')] and a['state'] == 'released' for a in store.records('assignment'))
    assert ledger.gate(run_id='run', phase='I', input_revision=manifest['input_revision'], checks_passed=True)['accepted']
