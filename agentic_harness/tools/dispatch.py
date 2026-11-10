"""Launch supported native providers after durable admission; retain originals.

This module never supplies credentials, invents effective metadata, uses a
fallback model, disables approval controls, or retries an uncertain launch.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import subprocess
import sqlite3
import uuid
from pathlib import Path

import coordination
import evidence
import plan_runtime
import intake
import lifecycle
import projects

RESULT_SCHEMA = plan_runtime.RESULT_SCHEMA


def command(provider, route, cwd, directory, readonly):
    if provider == 'codex':
        return ['codex', 'exec', '--model', route['model'], '-c', 'model_reasoning_effort=' + json.dumps(route['effort']),
                '-c', 'agents.enabled=false',
                '--json', '--cd', str(cwd), '--sandbox', 'read-only' if readonly else 'workspace-write',
                *(['--skip-git-repo-check'] if readonly else []),
                '--output-schema', str(directory / 'schema.json'), '--output-last-message', str(directory / 'native-result.json'), '-']
    if provider == 'claude':
        argv = ['claude', '--print', '--model', route['model'], '--effort', route['effort'], '--output-format', 'json',
                '--session-id', str(uuid.uuid4()), '--json-schema', json.dumps(RESULT_SCHEMA)]
        if readonly:
            argv += ['--tools', 'Read,Glob,Grep', '--strict-mcp-config']
        else:
            argv += ['--tools', 'Read,Glob,Grep,Bash,Edit,Write']
        return argv
    raise ValueError('unsupported provider')


def _write(path, value):
    with path.open('x') as out:
        out.write(json.dumps(value, indent=2, allow_nan=False) + '\n')
    path.chmod(0o600)


def _native_json(raw):
    def unique(pairs):
        value = {}
        for key, entry in pairs:
            if key in value:
                raise ValueError('duplicate native JSON field')
            value[key] = entry
        return value
    def nonfinite(value):
        raise ValueError('nonfinite native JSON constant')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)


def _provider(launch, prompt, cwd, directory, *, run=subprocess.run, prepared_argv=None):
    route = launch['effective']['requested']
    readonly = launch['effective']['permitted_writes'] == 'read_only' or (launch['effective']['permitted_writes'] == 'authorized_only' and not launch.get('owned_paths'))
    argv = prepared_argv if prepared_argv is not None else command(launch['provider'], route, cwd, directory, readonly)
    if prepared_argv is None:
        (directory / 'prompt.txt').write_text(prompt)
        (directory / 'prompt.txt').chmod(0o600)
        _write(directory / 'schema.json', RESULT_SCHEMA)
    try:
        # Preserve the admitted assignment, including validated effective settings.
        # The pre-admission intent remains separately retained and unchanged.
        _write(directory / 'invocation.json', {'argv': argv, 'cwd': str(cwd), 'launch': launch})
        process = run(argv, input=prompt, text=True, capture_output=True, cwd=cwd)
        (directory / 'stdout.txt').write_text(process.stdout)
        (directory / 'stderr.txt').write_text(process.stderr)
        status, usage = 'failed', {'cost': None, 'input_tokens': None, 'output_tokens': None, 'reasoning_tokens': None, 'tool_cost': None}
        result = {'complete': False, 'native_exit_code': process.returncode}
        if process.returncode == 0:
            result, errors = None, []
            try:
                if launch['provider'] == 'codex':
                    result = _native_json((directory / 'native-result.json').read_text())
                    # Keep JSONL usage exactly as reported; absence is unknown.
                    events = [_native_json(line) for line in process.stdout.splitlines() if line.strip()]
                    if any(not isinstance(event, dict) for event in events):
                        raise ValueError('native event must be an object')
                    usage['native_records'] = [event for event in events if 'usage' in event]
                else:
                    native = _native_json(process.stdout)
                    if not isinstance(native, dict):
                        raise ValueError('native result envelope must be an object')
                    usage['native_records'] = native.get('usage')
                    usage['cost'] = native.get('total_cost_usd')
                    result = native.get('structured_output')
                    if result is None:
                        result = _native_json(native['result'])
            except (OSError, ValueError, TypeError, KeyError) as exc:
                # The process is known to have stopped. Keep raw native files and
                # any parsed original; unavailable structured evidence stays null.
                errors.append(f'native result unavailable or malformed: {type(exc).__name__}')
            errors.extend(plan_runtime.result_errors(result, launch['input_revision']))
            complete = not errors and plan_runtime.result_complete(result, launch['input_revision'])
            status = 'success' if complete else 'incomplete'
            _write(directory / 'result-validation.json', {'complete': complete, 'errors': errors})
        _write(directory / 'original-result.json', result)
        _write(directory / 'usage.json', usage)
        return status, result, usage
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        # Never replay a possibly active writer. Operator reconciliation must
        # establish the process outcome and retain any available original return.
        result = {'complete': False, 'error_type': type(exc).__name__, 'outcome': 'unknown'}
        _write(directory / 'uncertain.json', result)
        return 'uncertain', result, {'cost': None}



def _ledger_state(path, run_id):
    """Inspect an existing ledger without constructor/schema/WAL mutations."""
    try:
        with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
            row = db.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise ValueError('dispatch run has no existing durable ledger')
        return json.loads(row[0])
    except sqlite3.Error as exc:
        raise ValueError(f'dispatch ledger unavailable: {exc}') from exc


def execute(request, *, run=subprocess.run):
    root = Path(request['worktree']).absolute()
    if root != root.resolve():
        raise ValueError('dispatch requires the canonical owned worktree path')
    destination = Path(request['evidence_dir']).absolute()
    if destination.exists() or destination.resolve().is_relative_to(root):
        raise ValueError('dispatch requires a new external evidence directory')
    bundle = Path(request['bundle']).resolve()
    manifest = evidence.verify(bundle, root)
    state = _ledger_state(request['ledger'], request['run_id'])
    if (manifest['project'], manifest['change'], manifest['run_id']) != (state['project'], state['change'], request['run_id']):
        raise ValueError('dispatch scope differs from retained inputs')
    if manifest.get('policy') != state['policy_version'] or (state['policy_version'] == 'plans-v1' and manifest.get('schema_version') != 3):
        raise ValueError('plans-v1 dispatch requires retained source schema 3 with current policy')
    admitted_intake = intake.validate_intake(json.loads(lifecycle.original(request['intake'], root)), root)
    if (admitted_intake['project'], admitted_intake['change']) != (state['project'], state['change']):
        raise ValueError('intake differs from run scope')
    registration = projects.resolve(admitted_intake['project'], root)
    if admitted_intake['ticket']:
        expected_change = root / registration['root'] / 'openspec/changes' / admitted_intake['change']
        if any(not (root / link).resolve().is_relative_to(expected_change) for link in admitted_intake['ticket']['spec_links']):
            raise ValueError('ticket specification links differ from registered change authority')
    c = request['coordination']
    store = coordination.CoordinationStore(root)
    if manifest['repository'] != store.repository_id:
        raise ValueError('dispatch retained repository differs from owned workspace')
    binding = coordination.validate_workspace_binding(store, c['qualified'], c['generation'], c['session'],
        root, state['project'], state['change'], request['run_id'], manifest['base_commit'])
    if coordination.environment_policy(registration['environment']) != binding['claim']['environment_policy']:
        raise ValueError('registered environment policy changed; start a new explicitly scoped run')
    live_revision = binding['source']['content_revision']
    if request['kind'] not in {'single', 'round'}:
        raise ValueError('dispatch kind must be single or round')
    paired = request['kind'] == 'round'
    payload = request['admission']
    # Do not let a different input claim acquire reservations or launch a worker.
    if payload['input_revision'] != manifest['input_revision']:
        raise ValueError('admission revision differs from retained inputs')
    sources = payload['reviewers'] if paired else [payload]
    steps = plan_runtime.REVIEW_STEPS.get(payload.get('phase'), ()) if paired else [payload['step']]
    if len(steps) != len(sources):
        raise ValueError('invalid phase or role inventory')
    descriptors = {step['id']: step for step in state['catalog']['steps']}
    modes = []
    active_change = root / registration['root'] / 'openspec/changes' / state['change']
    def planning_artifact(relative):
        target = projects.relative_path(root, relative)
        return (active_change.is_dir() and not target.is_dir() and target.is_relative_to(active_change)
                and (target.suffix == '.md' or target == active_change / '.openspec.yaml'))
    for source, step in zip(sources, steps):
        if step not in descriptors:
            raise ValueError('unknown assignment role')
        writes = descriptors[step]['permitted_writes']
        actions = admitted_intake['allowed_actions']
        if step == 'escalation' and 'escalate' not in actions:
            raise ValueError('escalation requires scoped explicit intake authority')
        if writes == 'read_only' or (writes == 'authorized_only' and not source.get('owned_paths')):
            modes.append('reviewer')
            if not set(actions) & {'planning', 'review', 'implementation'}:
                raise ValueError('read/review assignment exceeds intake authority')
        else:
            modes.append('writer')
            owned_paths = source.get('owned_paths')
            if not isinstance(owned_paths, list) or not owned_paths or any(not isinstance(p, str) or not p for p in owned_paths):
                raise ValueError('writer requires exact nonempty owned paths')
            for owned in owned_paths:
                canonical = projects.relative_path(root, owned)
                if canonical.relative_to(root).as_posix() != owned:
                    raise ValueError('owned writer paths must be canonical explicit files')
            if writes in {'assigned_design', 'assigned_specs'} and not all(planning_artifact(p) for p in owned_paths):
                raise ValueError('design writer is restricted to selected active change Markdown/.openspec.yaml')
            implementation_write = writes == 'assigned_code' or not all(planning_artifact(p) for p in owned_paths)
            if implementation_write and (admitted_intake['mode'] != 'implementation' or 'writer' not in actions
                                         or not admitted_intake['ticket'] or not admitted_intake['ticket']['verified']):
                raise ValueError('nonplanning/code writer requires verified implementation intake')
            if not implementation_write and not set(actions) & {'planning', 'implementation'}:
                raise ValueError('writer role exceeds intake mode')
            for owned in owned_paths:
                if not any(projects.scope_contains(scope, owned) for scope in admitted_intake['scope']):
                    raise ValueError('owned writer path exceeds authorized intake scope')
                if not any(projects.scope_contains(scope, owned) for scope in projects.editable_areas(registration)):
                    raise ValueError('owned writer path exceeds registered project areas')
    prompts = request['prompts']
    if not isinstance(prompts, list) or len(prompts) != len(sources) or len(sources) != (2 if paired else 1):
        raise ValueError('one original prompt is required for each assignment')
    if paired and (payload['phase'] not in {'D', 'I'} or not c.get('frozen')):
        raise ValueError('paired review requires a frozen coordination interval')
    for source in sources:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', source['launch_id']):
            raise ValueError('launch_id must be a safe external artifact identifier')
        if source['launch_id'] in state['launches']:
            raise ValueError('launch already admitted; reconcile original result instead of replaying')
    # Pin every original before any evidence write, reservation or ledger debit.
    pinned_prompts = []
    for filename in prompts:
        try:
            if not isinstance(filename, str) or not filename:
                raise ValueError('prompt requires an original file path')
            original = Path(filename).read_bytes()
            text = original.decode('utf-8')
            if not text.strip() or '\0' in text:
                raise ValueError('prompt must contain nonempty UTF-8 text without NUL')
        except (OSError, UnicodeError) as exc:
            raise ValueError(f'original prompt unavailable or invalid: {exc}') from exc
        pinned_prompts.append((original, text))
    destination.mkdir(parents=True)
    _write(destination / 'request.json', request)
    prepared = {}
    for source, step, mode, (original, text) in zip(sources, steps, modes, pinned_prompts):
        directory = destination / source['launch_id']
        directory.mkdir()
        original_file = directory / 'original-prompt.txt'
        original_file.write_bytes(original)
        original_file.chmod(0o600)
        boundary = {'project': state['project'], 'change': state['change'], 'run_id': request['run_id'],
                    'implementation_workspace': str(root), 'role': step, 'mode': mode,
                    'owned_paths': source.get('owned_paths', []), 'output_directory': str(directory),
                    'input_revision': manifest['input_revision'], 'retained_bundle': str(bundle),
                    'deleted_paths': sorted(manifest['deleted_files'])}
        prompt = text + '\n\nAssignment boundaries (mandatory):\n' + json.dumps(boundary, sort_keys=True)
        prompt += ('\nWrite only the exact owned paths in the named implementation workspace; preserve every other file.'
                   if mode == 'writer' else '\nDo not edit source or implementation files; use assigned external scratch space only.')
        prompt += '\nReturn the full structured result, complete coverage and input_revision=' + manifest['input_revision'] + '. Do not launch nested agents.\n'
        if manifest['deleted_files']:
            prompt += 'Review deleted originals under retained_bundle/deleted-source against the declared deletion paths.\n'
        (directory / 'prompt.txt').write_text(prompt)
        (directory / 'prompt.txt').chmod(0o600)
        _write(directory / 'schema.json', RESULT_SCHEMA)
        cwd = bundle / 'source' if mode == 'reviewer' else root
        route = state['routes'][step]['routes'][source['provider']]
        argv = command(source['provider'], route, cwd, directory, mode == 'reviewer')
        _write(directory / 'prepared-invocation.json', {'argv': argv, 'cwd': str(cwd), 'launch': source,
               'role': step, 'requested': route, 'original_prompt_sha256': hashlib.sha256(original).hexdigest()})
        prepared[source['launch_id']] = (prompt, cwd, argv)
    ledger = plan_runtime.Ledger(Path(request['ledger']))
    reserved = []
    try:
        for source, mode in zip(sources, modes):
            assignment = source['launch_id']
            directory = destination / assignment
            store.reserve(qualified=c['qualified'], generation=c['generation'], session=c['session'],
                          assignment_id=assignment, run=request['run_id'], files=sorted(set(manifest['input_scope']) | set(manifest['deleted_files'])) if mode == 'reviewer' else source['owned_paths'],
                          input_revision=live_revision, tests=request['tests'], output=str(directory),
                          authorization=c['authorization'], mode=mode)
            reserved.append(assignment)
        admitted = ledger.apply('start-round' if paired else 'start', {'run_id': request['run_id'], **payload})
        if admitted['replayed']:
            raise ValueError('duplicate admission; no provider replay')
    except Exception:
        for assignment in reserved:
            path = destination / assignment / 'not-launched.json'
            _write(path, {'status': 'not-launched', 'reason': 'admission failed'})
            store.settle(assignment, str(path), c['authorization'])
        # release_assignments itself refuses to release unsettled siblings.
        if reserved:
            store.release_assignments(request['run_id'], c['authorization'])
        raise
    launches = admitted['launches'] if paired else [admitted['launch']]
    def one(launch):
        directory = destination / launch['launch_id']
        prompt, cwd, argv = prepared[launch['launch_id']]
        status, result, usage = _provider(launch, prompt, cwd, directory, run=run, prepared_argv=argv)
        ledger.finish(run_id=request['run_id'], launch_id=launch['launch_id'], status=status, result=result, usage=usage)
        if status != 'uncertain':
            store.settle(launch['launch_id'], str(directory / 'original-result.json'), c['authorization'])
        return {'launch_id': launch['launch_id'], 'status': status, 'result': result}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(one, launches))
    _write(destination / 'results.json', results)
    if all(r['status'] != 'uncertain' for r in results):
        store.release_assignments(request['run_id'], c['authorization'])
    if paired:
        evidence.verify(bundle, root)
    return {'status': 'settled' if all(r['status'] != 'uncertain' for r in results) else 'incomplete', 'results': results}


def recover(request):
    """Settle a charged launch without starting a provider or releasing live siblings."""
    ledger = plan_runtime.Ledger(Path(request['ledger']))
    receipt = request['recovery']
    root = Path(request['worktree']).resolve()
    store = coordination.CoordinationStore(root)
    assignment = next((a for a in store.records('assignment') if a['id'] == receipt['launch_id']), None)
    state = ledger.status(receipt['run_id'])
    if not assignment or assignment['run'] != receipt['run_id'] or assignment['claim'] != state['project'] + ':' + state['change']:
        raise ValueError('recovery differs from owned assignment')
    result = ledger.apply('recover-launch', receipt)
    if assignment['state'] == 'running':
        store.settle(receipt['launch_id'], receipt['original_result']['path'], receipt['authority']['source'])
    active = [a for a in store.records('assignment') if a['run'] == receipt['run_id'] and a['state'] == 'running']
    if not active:
        store.release_assignments(receipt['run_id'], receipt['authority']['source'])
    return {'recovery': result, 'unsettled_siblings': [a['id'] for a in active]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--recover', action='store_true', help='reconcile one original charged launch; never call a provider')
    args = parser.parse_args(argv)
    try:
        print(json.dumps((recover if args.recover else execute)(json.loads(args.request.read_text())), indent=2))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({'status': 'blocked', 'reason': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
