#!/usr/bin/env python3
"""Fail-closed plan preflight and transactional, host-local run ledger.

No provider calls are made here. Commit start/start-round before invoking a native
worker; replayed=True is a reconciliation receipt, never permission to relaunch.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

import yaml
import evidence

CATALOG = Path(__file__).resolve().parents[1] / 'plans.yaml'
STEP_IDS = ('human', 'lead_plan', 'lookup', 'context', 'design_author',
            'design_contract', 'design_risk', 'adjudicator', 'design_fixer',
            'implementer', 'implementation_behavior', 'implementation_safety',
            'implementation_fixer', 'lead_verify', 'escalation')
REVIEW_STEPS = {'D': ('design_contract', 'design_risk'),
                'I': ('implementation_behavior', 'implementation_safety')}
ACTIVE = ('started', 'uncertain')
RESULT_SCHEMA = {'type': 'object', 'required': ['complete', 'coverage_complete', 'truncated', 'findings', 'input_revision'],
                 'properties': {'complete': {'type': 'boolean'}, 'coverage_complete': {'type': 'boolean'},
                                'truncated': {'type': 'boolean'}, 'findings': {'type': 'array', 'items': {'type': 'object'}},
                                'input_revision': {'type': 'string'}}}


def result_errors(result, expected_revision):
    """Validate returned evidence locally; provider-side schemas are not proof."""
    if not isinstance(result, dict):
        return ['result must be an object']
    errors = []
    for field in ('complete', 'coverage_complete', 'truncated'):
        if type(result.get(field)) is not bool:
            errors.append(f'{field} must be a boolean')
    findings = result.get('findings')
    if not isinstance(findings, list) or any(not isinstance(finding, dict) for finding in findings):
        errors.append('findings must be a list of objects')
    else:
        for finding in findings:
            if (finding.get('severity') in ('major', 'blocker')
                    and (not isinstance(finding.get('id'), str) or not finding['id'])):
                errors.append('serious finding needs a stable id')
    revision = result.get('input_revision')
    if not isinstance(revision, str) or not revision or revision != expected_revision:
        errors.append('input_revision must match the admitted assignment')
    return errors


def result_complete(result, expected_revision):
    return (not result_errors(result, expected_revision) and result['complete'] is True
            and result['coverage_complete'] is True and result['truncated'] is False)


class PlanError(ValueError):
    """A controlled configuration, authority, resource or evidence blocker."""


def require(condition, message):
    if not condition:
        raise PlanError(message)


def fields(obj, required, optional=()):
    require(isinstance(obj, dict), 'expected object')
    require(set(required) <= obj.keys(), f'missing fields: {sorted(set(required) - obj.keys())}')
    require(obj.keys() <= set(required) | set(optional),
            f'unknown fields: {sorted(obj.keys() - set(required) - set(optional))}')


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class StrictLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    pairs = loader.construct_pairs(node, deep=deep)
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate catalog field: {key}')
        result[key] = value
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_catalog(path=None):
    data = yaml.load(Path(path or CATALOG).read_text(), Loader=StrictLoader)
    fields(data, ('schema_version', 'policy_version', 'profile_version', 'default',
                  'source_date', 'max_workers', 'nested_delegation', 'profiles', 'steps', 'plans'))
    require(data['schema_version'] == 1 and data['profile_version'] == 1, 'unsupported schema/profile')
    require(data['policy_version'] == 'plans-v1' and data['default'] == 'balanced', 'unsupported policy/default')
    require(data['max_workers'] == 2 and data['nested_delegation'] is False, 'invalid concurrency policy')
    require(set(data['profiles']) == {'lookup', 'context', 'standard', 'deep'}, 'invalid profiles')
    for name, profile in data['profiles'].items():
        fields(profile, ('initial_tokens', 'working_tokens', 'result_tokens', 'handoff_tokens', 'requires_authority'))
        require(all(integer(profile[k], 1) for k in profile if k != 'requires_authority'), 'invalid profile tokens')
        require(profile['requires_authority'] is (name == 'deep'), 'invalid deep authority')
    require(isinstance(data['steps'], list) and tuple(s.get('id') for s in data['steps']) == STEP_IDS, 'invalid step inventory')
    for step in data['steps']:
        fields(step, ('id', 'label', 'scope', 'context_profile', 'permitted_writes', 'boundary'))
        require(step['context_profile'] in data['profiles'] or step['id'] == 'human', 'unknown context profile')
        require(all(isinstance(v, str) and v for v in step.values()), 'invalid step metadata')
    require(set(data['plans']) == {'budget', 'balanced', 'smart'}, 'invalid plan inventory')
    for name, plan in data['plans'].items():
        fields(plan, ('clean_rounds', 'steps'))
        require(plan['clean_rounds'] == (2 if name == 'smart' else 1), 'invalid clean minimum')
        require(set(plan['steps']) == set(STEP_IDS), 'invalid plan steps')
        for step, rule in plan['steps'].items():
            fields(rule, ('minimum', 'maximum', 'routes'))
            require(set(rule['routes']) == {'codex', 'claude'}, 'invalid providers')
            if step == 'human':
                require(rule == {'minimum': None, 'maximum': None, 'routes': {'codex': None, 'claude': None}}, 'human has model/budget')
                continue
            require(integer(rule['minimum']) and integer(rule['maximum']) and rule['minimum'] <= rule['maximum'], 'invalid limits')
            for provider, route in rule['routes'].items():
                fields(route, ('model', 'effort'))
                models = {'gpt-6-luna', 'gpt-6.1-sol', 'gpt-6-astra'} if provider == 'codex' else {'claude-haiku-5-5', 'claude-sonnet-5-5', 'claude-opus-5-5'}
                require(route['model'] in models and route['effort'] in {'low', 'medium', 'high', 'xhigh'}, 'invalid route')
        for lenses in REVIEW_STEPS.values():
            require(plan['steps'][lenses[0]] == plan['steps'][lenses[1]], 'conflicting shared review limits/routes')
    return data


def routes(plan='balanced', catalog=None):
    catalog = catalog or load_catalog()
    require(plan in catalog['plans'], 'unknown plan')
    return {'policy_version': catalog['policy_version'], 'policy_hash': digest(catalog),
            'plan': plan, 'steps': copy.deepcopy(catalog['plans'][plan]['steps']),
            'profiles': copy.deepcopy(catalog['profiles']), 'boundaries': copy.deepcopy(catalog['steps'])}


def context_fit(catalog, profile, context, provider, model, authority=None):
    fields(context, ('verified_window', 'input_tokens', 'tool_growth_tokens'),
           ('initial_tokens', 'profile', 'pricing_reassessed', 'capacity_source'))
    require(profile in catalog['profiles'], 'unknown context profile')
    require(integer(context['verified_window'], 1) and context.get('capacity_source'), 'unknown effective context capacity')
    require(integer(context['input_tokens']) and integer(context['tool_growth_tokens']), 'invalid context tokens')
    p = catalog['profiles'][profile]
    require(not p['requires_authority'] or (authority or {}).get('deep_context'), 'deep context needs authority')
    reserve = max(32000, math.ceil(.15 * context['verified_window']))
    target = min(p['working_tokens'], context['verified_window'] - reserve - context['tool_growth_tokens'])
    require(integer(context.get('initial_tokens', 0)) and context.get('initial_tokens', 0) <= p['initial_tokens'], 'initial context packet overflow')
    require(context['input_tokens'] <= target, 'context overflow; partition complete coverage or hand off')
    total = context['input_tokens'] + context['tool_growth_tokens']
    pricing = (model == 'claude-haiku-5-5' and total > 100000) or (provider == 'codex' and total > 272000)
    require(not pricing or context.get('pricing_reassessed') is True, 'pricing reassessment required')
    return {'profile': profile, 'reserve_tokens': reserve, 'input_target': target,
            'handoff_tokens': min(p['handoff_tokens'], context['verified_window'] - reserve),
            'pricing_reassessment': pricing}


def preflight(catalog=None, plan='balanced', step=None, provider=None, attestation=None, context=None, authority=None):
    catalog = catalog or load_catalog()
    rules = routes(plan, catalog)['steps']
    require(step in rules and step != 'human', 'unknown/non-agent step')
    require(provider in {'codex', 'claude'}, 'unknown provider')
    route = rules[step]['routes'][provider]
    fields(attestation, ('source', 'supported_models', 'supported_efforts', 'effective_model', 'effective_effort'),
           ('actual_model', 'actual_effort', 'overrides', 'native_options'))
    require(isinstance(attestation['source'], str) and attestation['source'], 'capability evidence required')
    require(isinstance(attestation['supported_models'], list) and route['model'] in attestation['supported_models'], 'required model unavailable')
    require(isinstance(attestation['supported_efforts'], dict) and route['effort'] in attestation['supported_efforts'].get(route['model'], []), 'required effort unavailable/unknown')
    require(attestation['effective_model'] == route['model'] and attestation['effective_effort'] == route['effort'], 'conflicting effective override')
    allowed_options = {'model', 'model_reasoning_effort'} if provider == 'codex' else {'model', 'effort'}
    overrides = attestation.get('overrides', [])
    require(isinstance(overrides, list), 'overrides must be a source-attributed list')
    for override in overrides:
        fields(override, ('source', 'model', 'effort'))
        require(override['source'] and override['model'] == route['model'] and override['effort'] == route['effort'], 'conflicting environment override')
    options = attestation.get('native_options', {})
    require(isinstance(options, dict) and options.keys() <= allowed_options, 'unsupported native option')
    require(all(v == route['model'] if k == 'model' else v == route['effort'] for k, v in options.items()), 'conflicting native option')
    for key in ('model', 'effort'):
        require(attestation.get(f'actual_{key}') in (None, route[key]), 'runtime-reported settings conflict')
    descriptor = next(s for s in catalog['steps'] if s['id'] == step)
    profile = (context or {}).get('profile', descriptor['context_profile'])
    require(profile == descriptor['context_profile'] or profile == 'deep', 'conflicting role context profile')
    fit = context_fit(catalog, profile, context, provider, route['model'], authority)
    return {'requested': copy.deepcopy(route), 'effective': {'model': attestation['effective_model'], 'effort': attestation['effective_effort']},
            'actual': {'model': attestation.get('actual_model'), 'effort': attestation.get('actual_effort')},
            'attestation': copy.deepcopy(attestation), 'context': fit, 'permitted_writes': descriptor['permitted_writes']}


class Ledger:
    """SQLite BEGIN IMMEDIATE serializes cross-process admission and receipts."""
    def __init__(self, path, catalog=None):
        self.path = str(path)
        self.catalog = catalog or load_catalog()
        require(self.path != ':memory:', 'ledger must be durable')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            con.execute('CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL)')

    @contextmanager
    def transaction(self, run_id, kind, request):
        with sqlite3.connect(self.path, timeout=30) as con:
            con.execute('PRAGMA synchronous=FULL')
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
            require(row is not None, 'unknown run')
            state = json.loads(row[0])
            yield state
            con.execute('UPDATE runs SET body=? WHERE id=?', (canonical(state), run_id))
            con.execute('INSERT INTO events(run_id,kind,body) VALUES(?,?,?)', (run_id, kind, canonical(request)))

    def init(self, *, run_id, project, change, slices, authority, input_revision, context, spend_envelope, applicable_steps, plan='balanced'):
        require(all(isinstance(x, str) and x for x in (run_id, project, change, input_revision)), 'missing run identity')
        require(isinstance(slices, list) and slices and len(set(slices)) == len(slices) and all(isinstance(s, str) and s for s in slices), 'pin unique nonempty slice inventory')
        require(isinstance(authority, dict) and authority.get('scope') and authority.get('approved_by'), 'missing scoped human authority')
        fields(spend_envelope, ('ceiling', 'currency', 'unknown_cost_policy'), ('premium_authorized',))
        ceiling = spend_envelope['ceiling']
        require(ceiling is None or (type(ceiling) in (int, float) and math.isfinite(ceiling) and ceiling >= 0), 'invalid spend ceiling')
        require(spend_envelope['unknown_cost_policy'] in {'block', 'retain'}, 'unknown cost policy required')
        require(isinstance(context, dict) and spend_envelope['currency'], 'context/currency required')
        require((isinstance(applicable_steps, list) and len(set(applicable_steps)) == len(applicable_steps) and all(step in STEP_IDS and step != 'human' for step in applicable_steps)), 'invalid applicable step inventory')
        route_data = routes(plan, self.catalog)
        limits = {k: v['maximum'] for k, v in route_data['steps'].items() if k != 'human'}
        limits['D'] = limits.pop('design_contract'); limits.pop('design_risk')
        limits['I'] = limits.pop('implementation_behavior'); limits.pop('implementation_safety')
        for slice_id in slices:
            limits[f'implementer:{slice_id}'] = limits['implementer']
        for phase in REVIEW_STEPS:
            limits[f'adjudicator:{phase}'] = limits['adjudicator']
        state = {'run_id': run_id, 'project': project, 'change': change, 'plan': plan,
                 'policy_version': self.catalog['policy_version'], 'policy_hash': digest(self.catalog),
                 'catalog': self.catalog, 'slices': slices, 'authority': authority, 'input_revision': input_revision,
                 'context': context, 'spend_envelope': spend_envelope, 'routes': route_data['steps'],
                 'phase_revisions': {'D': input_revision, 'I': input_revision}, 'applicable_steps': applicable_steps,
                 'limits': limits, 'attempts': {}, 'launches': {}, 'rounds': [], 'extensions': {},
                 'usage': [], 'disputes': {}, 'checkpoints': {}, 'history': [], 'checks': {}}
        with sqlite3.connect(self.path, timeout=30) as con:
            con.execute('BEGIN IMMEDIATE')
            existing = con.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
            require(existing is None, 'run already exists; resume instead')
            con.execute('INSERT INTO runs VALUES(?,?)', (run_id, canonical(state)))
            con.execute('INSERT INTO events(run_id,kind,body) VALUES(?,?,?)', (run_id, 'init', canonical(state)))
        return self.status(run_id)

    def status(self, run_id):
        with sqlite3.connect(self.path) as con:
            row = con.execute('SELECT body FROM runs WHERE id=?', (run_id,)).fetchone()
        require(row is not None, 'unknown run')
        state = json.loads(row[0])
        effective = self._accounted_usage(state)
        known = sum(u['record'].get('cost', 0) or 0 for u in effective)
        unknown = sum(u['record'].get('cost') is None for u in effective)
        state['accounting'] = {'known_cost': known, 'unknown_cost_records': unknown, 'total_cost': None if unknown else known, 'effective_receipt_ids': [u['receipt_id'] for u in effective]}
        return state

    def _accounted_usage(self, state):
        return [u for u in state['usage'] if not u.get('superseded_by')]

    def _active(self, state):
        return [v for v in state['launches'].values() if v['status'] in ACTIVE]

    def _slots(self, con_state, extra):
        # Aggregate across every logical run sharing this host-local ledger.
        with sqlite3.connect(self.path) as con:
            others = con.execute('SELECT body FROM runs WHERE id != ?', (con_state['run_id'],)).fetchall()
        count = len(self._active(con_state)) + sum(len(self._active(json.loads(r[0]))) for r in others)
        require(count + extra <= 2, 'two aggregate worker slots exhausted')

    def _key(self, state, step, slice_id=None, phase=None):
        if step == 'implementer':
            require(slice_id in state['slices'], 'undeclared implementation slice')
            return f'{step}:{slice_id}', f'{step}:{slice_id}'
        if step == 'adjudicator':
            require(phase in REVIEW_STEPS, 'adjudicator needs phase')
            return f'{step}:{phase}', f'{step}:{phase}'
        return step, step

    def _spend(self, state, estimate, premium):
        envelope = state['spend_envelope']
        require(not premium or envelope.get('premium_authorized') is True, 'premium processing requires spend authority')
        require(estimate is None or (type(estimate) in (int, float) and math.isfinite(estimate) and estimate >= 0), 'invalid estimated cost')
        if envelope['ceiling'] is None:
            return
        actual = sum(u['record'].get('cost', 0) or 0 for u in self._accounted_usage(state))
        reservations = sum(v.get('estimated_cost') or 0 for v in state['launches'].values() if v['status'] in ACTIVE)
        unknown = any(u['record'].get('cost') is None for u in self._accounted_usage(state))
        require(not (unknown or estimate is None) or envelope['unknown_cost_policy'] == 'retain', 'unknown cost blocks bounded spend')
        require(actual + reservations + (estimate or 0) <= envelope['ceiling'], 'spend envelope exhausted')

    def _prepare(self, state, payload, step, expected_revision=None):
        fields(payload, ('launch_id', 'provider', 'identity', 'input_revision', 'attestation', 'context'),
               ('slice_id', 'phase', 'parent_launch_id', 'estimated_cost', 'premium', 'owned_paths', 'escalation', 'material_edit', 'findings'))
        require(payload.get('parent_launch_id') is None, 'nested delegation forbidden')
        require(all(isinstance(payload[k], str) and payload[k] for k in ('launch_id', 'identity', 'input_revision')), 'invalid launch identity')
        require(payload['identity'] not in {v['identity'] for v in state['launches'].values()}, 'worker identity must be fresh')
        require(payload['input_revision'] == (expected_revision or state['input_revision']), 'input revision changed; reconcile first')
        require(type(payload.get('premium', False)) is bool and type(payload.get('material_edit', False)) is bool, 'processing/edit flags must be booleans')
        self._spend(state, payload.get('estimated_cost'), payload.get('premium', False))
        effective = preflight(state['catalog'], state['plan'], step, payload['provider'], payload['attestation'], payload['context'], state['authority'])
        owned = payload.get('owned_paths', [])
        require(isinstance(owned, list) and all(isinstance(p, str) and p and '..' not in Path(p).parts and not Path(p).is_absolute() for p in owned), 'invalid owned paths')
        if effective['permitted_writes'] == 'read_only':
            require(not owned, 'reviewer/scout/adjudicator is read-only')
        elif effective['permitted_writes'] != 'authorized_only':
            require(owned, 'writer requires exclusive owned paths')
        for active in self._active(state):
            require(not any(a == b or a.startswith(b + '/') or b.startswith(a + '/') for a in owned for b in active.get('owned_paths', [])), 'overlapping writer ownership')
        if step == 'adjudicator':
            findings = payload.get('findings')
            require(isinstance(findings, list) and findings and all(isinstance(f, dict) and isinstance(f.get('id'), str) and f['id'] for f in findings), 'adjudicator requires complete nonempty findings batch')
            require(len({f['id'] for f in findings}) == len(findings), 'duplicate findings must be grouped deterministically')
        if step == 'escalation':
            esc = payload.get('escalation')
            fields(esc, ('question', 'approaches', 'evidence', 'allowed_files', 'maximum_calls', 'stopping_condition'))
            require(all(esc[k] for k in ('question', 'approaches', 'evidence', 'stopping_condition')) and isinstance(esc['allowed_files'], list) and esc['maximum_calls'] == 1 and owned == esc['allowed_files'], 'invalid bounded escalation')
            require(any(receipt.get('escalation') == esc for receipt in state['extensions'].values()), 'named escalation question/files need matching human receipt')
        return dict(payload, step=step, status='started', effective=effective, result=None)

    def start(self, *, run_id, launch_id, step, **kwargs):
        payload = dict(kwargs, launch_id=launch_id)
        require(step not in sum((list(v) for v in REVIEW_STEPS.values()), []), 'use start-round for paired reviews')
        request = dict(payload, step=step)
        with self.transaction(run_id, 'start', request) as state:
            if launch_id in state['launches']:
                existing = state['launches'][launch_id]
                require(existing['request_hash'] == digest(request), 'conflicting duplicate launch id')
                return {'replayed': True, 'launch': existing}
            require(not any(r['status'] == 'started' for r in state['rounds']), 'review siblings must settle before dependent work')
            key, limit = self._key(state, step, payload.get('slice_id'), payload.get('phase'))
            require(limit in state['limits'], 'unknown step')
            require(state['attempts'].get(key, 0) < state['limits'][limit], 'attempt allowance exhausted; extension required')
            if step in {'design_fixer', 'implementation_fixer'}:
                phase = 'D' if step == 'design_fixer' else 'I'
                used = sum(r['phase'] == phase for r in state['rounds'])
                minimum = state['catalog']['plans'][state['plan']]['clean_rounds']
                require(state['limits'][phase] - used >= minimum, 'insufficient post-repair clean review capacity')
            self._slots(state, 1)
            launch = self._prepare(state, payload, step)
            launch['request_hash'] = digest(request)
            if step in {'design_author', 'design_fixer', 'implementer', 'implementation_fixer'} or payload.get('material_edit'):
                affected = 'D' if step in {'design_author', 'design_fixer'} else 'I'
                if step == 'lead_verify' and payload.get('material_edit'):
                    repair = 'implementation_fixer'
                    require(state['attempts'].get(repair, 0) < state['limits'][repair], 'integration edit requires repair allowance')
                    used = sum(r['phase'] == affected for r in state['rounds'])
                    require(state['limits'][affected] - used >= state['catalog']['plans'][state['plan']]['clean_rounds'], 'integration edit needs post-repair review capacity')
                    state['attempts'][repair] = state['attempts'].get(repair, 0) + 1
                for prior_round in state['rounds']:
                    if prior_round['phase'] == affected:
                        prior_round['invalidated'] = True
            state['attempts'][key] = state['attempts'].get(key, 0) + 1
            state['launches'][launch_id] = launch
            return {'replayed': False, 'launch': launch}

    def start_round(self, *, run_id, round_id, phase, input_revision, reviewers):
        request = dict(round_id=round_id, phase=phase, input_revision=input_revision, reviewers=reviewers)
        with self.transaction(run_id, 'start-round', request) as state:
            existing = next((r for r in state['rounds'] if r['round_id'] == round_id), None)
            if existing:
                require(existing['request_hash'] == digest(request), 'conflicting duplicate round')
                return {'replayed': True, 'round': existing, 'launches': [state['launches'][i] for i in existing['launch_ids']]}
            require(phase in REVIEW_STEPS and isinstance(reviewers, list) and len(reviewers) == 2, 'exactly two review lenses required')
            require(input_revision == state['phase_revisions'][phase], 'round revision mismatch')
            require(not self._active(state), 'settle siblings before review')
            require(sum(r['phase'] == phase for r in state['rounds']) < state['limits'][phase], 'shared review round ceiling exhausted')
            require(len({r['launch_id'] for r in reviewers}) == 2 and all(r['launch_id'] not in state['launches'] for r in reviewers), 'duplicate review launch id')
            self._slots(state, 2)
            launches = []
            for step, payload in zip(REVIEW_STEPS[phase], reviewers):
                require(payload['input_revision'] == input_revision, 'lenses must share frozen bytes')
                launch = self._prepare(state, payload, step, input_revision)
                launch['request_hash'] = digest(dict(payload, step=step))
                launch['round_id'] = round_id
                state['launches'][payload['launch_id']] = launch
                launches.append(launch)
            round_ = dict(round_id=round_id, phase=phase, input_revision=input_revision,
                          launch_ids=[v['launch_id'] for v in launches], status='started', clean=False, request_hash=digest(request))
            state['rounds'].append(round_)
            return {'replayed': False, 'round': round_, 'launches': launches}

    def finish(self, *, run_id, launch_id, status, result, usage):
        request = dict(launch_id=launch_id, status=status, result=result, usage=usage)
        require(status in {'success', 'failed', 'interrupted', 'uncertain', 'incomplete'}, 'invalid launch status')
        canonical(result)  # Preserve the exact parsed JSON value, including malformed nonobjects.
        with self.transaction(run_id, 'finish', request) as state:
            require(launch_id in state['launches'], 'unknown launch')
            launch = state['launches'][launch_id]
            if launch.get('finish_hash'):
                require(launch['finish_hash'] == digest(request), 'conflicting finish receipt')
                return {'replayed': True, 'launch': launch}
            self._usage(state, 'launch:' + launch_id, usage, launch_id)
            resolved_status = 'incomplete' if status == 'success' and not result_complete(result, launch['input_revision']) else status
            launch.update(status=resolved_status, result=result, finish_hash=digest(request),
                          result_validation={'errors': result_errors(result, launch['input_revision']),
                                             'complete': result_complete(result, launch['input_revision'])})
            self._settled_result(state, launch_id)
            return {'replayed': False, 'launch': launch}

    def _settled_result(self, state, launch_id):
        launch = state['launches'][launch_id]
        result = launch['result'] if isinstance(launch['result'], dict) else {}
        if launch['step'] in sum((list(v) for v in REVIEW_STEPS.values()), []):
            for finding in result.get('findings', []) if isinstance(result.get('findings'), list) else []:
                if isinstance(finding, dict) and finding.get('severity') in ('major', 'blocker'):
                    finding_id = finding.get('id')
                    if not isinstance(finding_id, str) or not finding_id:
                        continue  # Malformed evidence remains incomplete; never invent finding identity.
                    state['disputes'][finding_id] = dict(severity=finding['severity'], status='disputed', evidence=finding, independent_round_id=None, after_round_count=len(state['rounds']), phase=next(r['phase'] for r in state['rounds'] if r['round_id'] == launch['round_id']))
        for round_ in state['rounds']:
            if launch_id not in round_['launch_ids']:
                continue
            siblings = [state['launches'][i] for i in round_['launch_ids']]
            if all(v['status'] not in ACTIVE for v in siblings):
                round_['status'] = 'complete' if all(v['status'] == 'success' for v in siblings) else 'incomplete'
                round_['clean'] = round_['status'] == 'complete' and all(result_complete(v['result'], round_['input_revision']) and v['result']['findings'] == [] for v in siblings)

    def _verified_json(self, reference):
        fields(reference, ('path', 'sha256'))
        path = Path(reference['path'])
        require(path.is_absolute() and not path.is_symlink() and path.is_file(), 'recovery reference must be an existing absolute original file')
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == reference['sha256'], 'recovery evidence hash mismatch')
        data = json.loads(raw)
        require(isinstance(data, dict), 'recovery evidence must be an object')
        return data

    def recover_launch(self, *, run_id, launch_id, receipt_id, status, original_result,
                       process_evidence, authority, usage_reference, usage_complete):
        """Settle a charged existing launch from originals; never invoke a worker.

        usage_complete attests that the retained usage is cumulative for this
        launch. It supersedes earlier billing receipts only when final known
        cost covers their known subtotal. Raw prior receipts remain retained.
        """
        require(status in {'success', 'failed', 'interrupted', 'incomplete'}, 'recovery requires a known terminal status')
        require(isinstance(receipt_id, str) and receipt_id and type(usage_complete) is bool, 'bounded recovery receipt required')
        fields(authority, ('approved_by', 'scope', 'source'), ('project', 'change'))
        require(all(authority[k] for k in ('approved_by', 'scope', 'source')), 'explicit recovery authority required')
        result = self._verified_json(original_result)
        observed = self._verified_json(process_evidence)
        usage = self._verified_json(usage_reference)
        fields(observed, ('run_id', 'launch_id', 'input_revision', 'process_stopped', 'status', 'source', 'original_result_sha256', 'usage_sha256'))
        require(observed['run_id'] == run_id and observed['launch_id'] == launch_id and observed['process_stopped'] is True and observed['status'] == status and observed['source'], 'process outcome is not reconciled/stopped for this launch')
        require(observed['original_result_sha256'] == original_result['sha256'] and observed['usage_sha256'] == usage_reference['sha256'], 'reconciled process evidence does not bind supplied originals')
        require(usage_complete or usage.get('cost') is None, 'known cumulative billing requires explicit complete usage reconciliation')
        request = dict(launch_id=launch_id, receipt_id=receipt_id, status=status, original_result=original_result,
                       process_evidence=process_evidence, authority=authority, usage_reference=usage_reference,
                       usage_complete=usage_complete)
        with self.transaction(run_id, 'recover-launch', request) as state:
            require(authority['scope'] == state['authority']['scope'] and all(authority.get(k, state[k]) == state[k] for k in ('project', 'change')), 'recovery authority scope mismatch')
            recoveries = state.setdefault('recoveries', {})
            old = recoveries.get(receipt_id)
            if old:
                require(old['request_hash'] == digest(request), 'conflicting recovery receipt')
                return {'replayed': True, 'launch': state['launches'][launch_id], 'recovery': old}
            require(launch_id in state['launches'], 'unknown recovery launch')
            launch = state['launches'][launch_id]
            require(launch['status'] in ACTIVE, 'only an existing unresolved launch can be recovered')
            require(observed['input_revision'] == launch['input_revision'], 'stale process evidence revision')
            require(result.get('input_revision', launch['input_revision']) == launch['input_revision'], 'stale original result revision')
            require(status != 'success' or result.get('input_revision') == launch['input_revision'], 'successful recovery needs original input revision')
            prior = copy.deepcopy(launch)
            billing = [u for u in self._accounted_usage(state) if u['launch_id'] == launch_id]
            known = sum(u['record'].get('cost', 0) or 0 for u in billing)
            usage_id = 'recovery:' + receipt_id
            self._usage(state, usage_id, usage, launch_id)
            if usage_complete and usage.get('cost') is not None:
                require(usage['cost'] >= known, 'final usage cannot hide previously known billed cost')
            if usage_complete:
                for entry in billing:
                    if usage.get('cost') is not None or entry['record'].get('cost') is None:
                        entry['superseded_by'] = usage_id
            resolved_status = 'incomplete' if status == 'success' and not result_complete(result, launch['input_revision']) else status
            launch.update(status=resolved_status, result=result, recovery_receipt_id=receipt_id,
                          result_validation={'errors': result_errors(result, launch['input_revision']),
                                             'complete': result_complete(result, launch['input_revision'])})
            self._settled_result(state, launch_id)
            recovery = dict(request_hash=digest(request), request=request, prior_launch=prior,
                            preserved_attempts=copy.deepcopy(state['attempts']), resolved_status=resolved_status,
                            retained_original_result=result, retained_usage=usage)
            recoveries[receipt_id] = recovery
            return {'replayed': False, 'launch': launch, 'recovery': recovery}

    def _usage(self, state, receipt_id, record, launch_id=None):
        require(isinstance(record, dict), 'usage must retain known and unknown fields')
        if record.get('cost') is not None:
            require(type(record['cost']) in (int, float) and math.isfinite(record['cost']) and record['cost'] >= 0, 'invalid cost')
        entry = {'receipt_id': receipt_id, 'launch_id': launch_id, 'record': record}
        existing = next((u for u in state['usage'] if u['receipt_id'] == receipt_id), None)
        if existing:
            require(all(existing[k] == entry[k] for k in ('receipt_id', 'launch_id', 'record')), 'conflicting usage receipt')
        else:
            state['usage'].append(entry)

    def usage(self, *, run_id, receipt_id, record, launch_id=None):
        with self.transaction(run_id, 'usage', dict(receipt_id=receipt_id, record=record)) as state:
            if launch_id:
                require(launch_id in state['launches'], 'unknown usage launch')
            self._usage(state, receipt_id, record, launch_id)
        return self.status(run_id)['usage']

    def gate(self, *, run_id, phase, input_revision, checks_passed):
        state = self.status(run_id)
        require(phase in REVIEW_STEPS, 'unknown review phase')
        require(type(checks_passed) is bool, 'checks must be explicitly verified')
        streak = 0
        for round_ in reversed([r for r in state['rounds'] if r['phase'] == phase]):
            if not round_['clean'] or round_.get('invalidated') or round_['input_revision'] != input_revision:
                break
            streak += 1
        minimum = state['catalog']['plans'][state['plan']]['clean_rounds']
        blockers = []
        if input_revision != state['phase_revisions'][phase]: blockers.append('changed_final_bytes')
        if state['applicable_steps'] is None:
            blockers.append('applicable_steps_undeclared')
        else:
            for step in state['applicable_steps']:
                if step in sum((list(v) for v in REVIEW_STEPS.values()), []):
                    continue
                design_steps = {'lead_plan', 'lookup', 'context', 'design_author', 'design_fixer'}
                if phase == 'D' and step not in design_steps:
                    continue
                step_minimum = state['catalog']['plans'][state['plan']]['steps'][step]['minimum']
                scopes = state['slices'] if step == 'implementer' else [None]
                for slice_id in scopes:
                    successful = sum(v['step'] == step and v['status'] == 'success'
                                     and result_complete(v['result'], v['input_revision'])
                                     and (slice_id is None or v.get('slice_id') == slice_id)
                                     for v in state['launches'].values())
                    if successful < step_minimum:
                        blockers.append(f'missing_successful_step:{step}' + (f':{slice_id}' if slice_id else ''))
        if self._active(state): blockers.append('workers_unsettled')
        if streak < minimum: blockers.append('insufficient_clean_rounds')
        if not checks_passed: blockers.append('required_checks')
        if any(v['status'] != 'resolved' for v in state['disputes'].values()): blockers.append('serious_dispute')
        envelope = state['spend_envelope']
        if envelope['ceiling'] is not None:
            if sum(u['record'].get('cost', 0) or 0 for u in self._accounted_usage(state)) > envelope['ceiling']: blockers.append('spend_exceeded')
            if envelope['unknown_cost_policy'] == 'block' and any(u['record'].get('cost') is None for u in self._accounted_usage(state)): blockers.append('unknown_cost')
        return {'accepted': not blockers, 'status': 'accepted' if not blockers else 'incomplete', 'blockers': blockers, 'clean_streak': streak, 'minimum': minimum}

    def extension(self, *, run_id, receipt):
        fields(receipt, ('receipt_id', 'approved', 'approved_by', 'reason', 'evidence', 'used_allowed', 'completed', 'remaining', 'additional', 'resulting_ceilings', 'routes', 'estimates', 'stopping_condition'), ('spend_ceiling', 'escalation'))
        require(receipt['approved'] is True and all(receipt[k] for k in ('receipt_id', 'approved_by', 'reason', 'evidence', 'completed', 'remaining', 'stopping_condition')), 'no affirmative bounded extension')
        fields(receipt['estimates'], ('usage', 'cost', 'time'))
        with self.transaction(run_id, 'extension', receipt) as state:
            old = state['extensions'].get(receipt['receipt_id'])
            if old:
                require(old == receipt, 'conflicting extension receipt')
                return old
            require(receipt['routes'] == state['routes'], 'extension must disclose both current provider routes')
            require(isinstance(receipt['additional'], dict) and receipt['additional'], 'missing exact additional counts')
            require(set(receipt['additional']) == set(receipt['resulting_ceilings']) == set(receipt['used_allowed']), 'incomplete extension counts')
            for step, extra in receipt['additional'].items():
                require(step in state['limits'] and step not in {'implementer', 'adjudicator'} and integer(extra, 1), 'invalid extension step/count; use exact slice or phase key')
                used = sum(r['phase'] == step for r in state['rounds']) if step in REVIEW_STEPS else sum(v for k, v in state['attempts'].items() if k == step or k.startswith(step + ':'))
                require(receipt['used_allowed'][step] == {'used': used, 'allowed': state['limits'][step]}, 'stale extension counts')
                require(receipt['resulting_ceilings'][step] == state['limits'][step] + extra, 'conflicting resulting ceiling')
                state['limits'][step] += extra
            if 'spend_ceiling' in receipt:
                value = receipt['spend_ceiling']
                old_ceiling = state['spend_envelope']['ceiling']
                require(type(value) in (int, float) and math.isfinite(value) and old_ceiling is not None and value >= old_ceiling, 'invalid spend extension')
                state['spend_envelope']['ceiling'] = value
            state['extensions'][receipt['receipt_id']] = receipt
        return receipt

    def switch(self, *, run_id, plan, input_revision, reason):
        with self.transaction(run_id, 'switch', dict(plan=plan, input_revision=input_revision, reason=reason)) as state:
            require(not self._active(state), 'settle all workers before reconciliation')
            require(plan in state['catalog']['plans'] and input_revision and reason, 'invalid reconciliation')
            state['history'].append({'plan': state['plan'], 'input_revision': state['input_revision'], 'reason': reason})
            # Switching never mints ceilings. Only a complete extension receipt can.
            state['plan'] = plan
            state['routes'] = routes(plan, state['catalog'])['steps']
            state['input_revision'] = input_revision
            state['phase_revisions'] = {'D': input_revision, 'I': input_revision}
        return self.status(run_id)

    def reconcile(self, *, run_id, input_revision, phase_revisions, reason, snapshot_references):
        require(isinstance(phase_revisions, dict) and phase_revisions and phase_revisions.keys() <= REVIEW_STEPS.keys() and all(isinstance(v, str) and v for v in phase_revisions.values()), 'invalid phase revision mapping')
        require(isinstance(snapshot_references, dict) and snapshot_references and reason and input_revision, 'verified retained snapshot references required')
        require(snapshot_references.keys() == phase_revisions.keys(), 'each changed phase needs its own bound snapshot')
        with self.transaction(run_id, 'reconcile', dict(input_revision=input_revision, phase_revisions=phase_revisions, reason=reason, snapshot_references=snapshot_references)) as state:
            require(not self._active(state), 'settle all workers before reconciliation')
            for phase, reference in snapshot_references.items():
                fields(reference, ('path', 'sha256'))
                path = Path(reference['path'])
                require(path.name == 'manifest.json' and not path.is_symlink(), 'unsupported phase snapshot reference; expected original manifest.json')
                require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == reference['sha256'], 'snapshot reference missing/changed')
                try:
                    manifest = evidence.verify(path.parent)
                except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
                    raise PlanError(f'unsupported phase snapshot or retained source changed: {exc}') from exc
                require(manifest.get('schema_version') in (3, 4), 'new-plan reconciliation requires schema 3 or 4 retained evidence')
                require(all(manifest.get(k) == state[k] for k in ('project', 'change', 'run_id')), 'snapshot task identity mismatch')
                require(manifest.get('input_revision') == phase_revisions[phase], 'snapshot phase revision mismatch')
            state['history'].append({'input_revision': state['input_revision'], 'phase_revisions': copy.deepcopy(state['phase_revisions']), 'reason': reason, 'snapshot_references': snapshot_references})
            state['input_revision'] = input_revision
            state['phase_revisions'].update(phase_revisions)
        return self.status(run_id)

    def dispute(self, *, run_id, finding_id, severity, status, evidence, independent_round_id=None, phase='I'):
        require(phase in REVIEW_STEPS and severity in {'major', 'blocker'} and status in {'disputed', 'resolved'} and evidence, 'invalid serious dispute')
        with self.transaction(run_id, 'dispute', dict(finding_id=finding_id, status=status, evidence=evidence)) as state:
            if status == 'resolved':
                require(finding_id in state['disputes'], 'unknown dispute')
                require(any(r['phase'] == state['disputes'][finding_id].get('phase', phase) and i >= state['disputes'][finding_id].get('after_round_count', 0) and r['round_id'] == independent_round_id and r['clean'] and not r.get('invalidated') and r['input_revision'] == state['phase_revisions'][r['phase']] for i, r in enumerate(state['rounds'])), 'fresh independent acceptance required')
            state['disputes'][finding_id] = dict(severity=severity, status=status, evidence=evidence, independent_round_id=independent_round_id, after_round_count=state['disputes'].get(finding_id, {}).get('after_round_count', len(state['rounds'])), phase=state['disputes'].get(finding_id, {}).get('phase', phase))
        return self.status(run_id)['disputes']

    def checkpoint(self, *, run_id, checkpoint_id, record):
        fields(record, ('project', 'change', 'task', 'worktree', 'base', 'head', 'files', 'decisions', 'open_findings', 'checks', 'next_action', 'original_results', 'ownership'))
        with self.transaction(run_id, 'checkpoint', dict(checkpoint_id=checkpoint_id, record=record)) as state:
            require(record['project'] == state['project'] and record['change'] == state['change'], 'checkpoint identity mismatch')
            self._references(record)
            require(checkpoint_id not in state['checkpoints'] or state['checkpoints'][checkpoint_id]['record'] == record, 'conflicting checkpoint')
            state['checkpoints'][checkpoint_id] = {'record': record, 'usage_hash': digest(state['usage']), 'attempts': copy.deepcopy(state['attempts']), 'input_revision': state['input_revision']}
        return self.status(run_id)['checkpoints'][checkpoint_id]

    def _references(self, record):
        require(isinstance(record['files'], dict) and record['files'] and isinstance(record['original_results'], dict) and record['original_results'], 'checkpoint hash maps required')
        require(not (record['files'].keys() & record['original_results'].keys()), 'checkpoint source and original-result references overlap')
        for path, expected in (record['files'] | record['original_results']).items():
            p = Path(path)
            require(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == expected, f'checkpoint reference missing/changed: {path}')
        require(isinstance(record['ownership'], dict) and record['ownership'], 'checkpoint ownership required')
        require(Path(record['worktree']).is_dir(), 'checkpoint worktree unavailable')

    def resume(self, *, run_id, checkpoint_id, input_revision, ownership):
        state = self.status(run_id)
        require(checkpoint_id in state['checkpoints'], 'unknown checkpoint')
        check = state['checkpoints'][checkpoint_id]
        self._references(check['record'])
        require(ownership == check['record']['ownership'], 'reconcile changed ownership before writing')
        require(input_revision == check['input_revision'] == state['input_revision'], 'reconcile changed revision before writing')
        require(not self._active(state), 'uncertain/live launches require reconciliation; never replay')
        return {'resumed': True, 'run': state}

    def apply(self, command, request):
        require(command in {'init', 'start', 'finish', 'recover-launch', 'start-round', 'gate', 'extension', 'switch', 'reconcile', 'checkpoint', 'resume', 'usage', 'dispute', 'status'}, 'unknown command')
        return getattr(self, command.replace('-', '_'))(**request)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db')
    parser.add_argument('--catalog', default=str(CATALOG))
    parser.add_argument('command', choices=['routes', 'preflight', 'init', 'start', 'finish', 'recover-launch', 'start-round', 'gate', 'extension', 'switch', 'reconcile', 'checkpoint', 'resume', 'usage', 'dispute', 'status'])
    parser.add_argument('--plan', default='balanced')
    parser.add_argument('--request', default='-', help='JSON request file, or - for stdin')
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        if args.command == 'routes':
            result = routes(args.plan, catalog)
        else:
            request = json.loads(sys.stdin.read() if args.request == '-' else Path(args.request).read_text())
            require(isinstance(request, dict), 'request must be an object')
            if args.command == 'preflight':
                result = preflight(catalog=catalog, **request)
            else:
                require(args.db, '--db required for persistent operations')
                result = Ledger(args.db, catalog).apply(args.command, request)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (PlanError, ValueError, TypeError, KeyError, OSError, yaml.YAMLError, sqlite3.Error) as exc:
        print(json.dumps({'status': 'incomplete', 'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
