"""Prepared GitHub operations with scoped authority and durable reconciliation.

No operation is retried merely because a response was lost. This journal stores
receipts, not secrets or provider conversations. Use a host-local external path.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from markdown_it import MarkdownIt

import evidence
import intake
import projects

ACTIONS = {'issue', 'comment', 'pr', 'edit-issue', 'edit-pr', 'push', 'ready', 'merge'}
EVENTS = {'scope', 'decision', 'blocker-resolution', 'review-response', 'final-handoff'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def original(ref, root):
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise ValueError('original evidence needs path and hash')
    path = Path(ref['path'])
    if not path.is_absolute() or path.is_symlink() or path.resolve().is_relative_to(root):
        raise ValueError('original evidence must be an external regular file')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref['sha256']:
        raise ValueError('original evidence hash mismatch')
    return raw


def permitted(authority: dict, action: str, project: str, change: str) -> bool:
    return (isinstance(authority, dict) and isinstance(authority.get('source'), str) and bool(authority['source'])
            and authority.get('project') == project and authority.get('change') == change
            and action in authority.get('actions', []))


def prepare_ticket(*, problem, outcome, scope, acceptance, project, change, specs, dependencies, relationships):
    values = locals()
    if any(not isinstance(values[k], str) or not values[k].strip() for k in ('problem', 'outcome', 'scope', 'project', 'change')):
        raise ValueError('ticket needs bounded problem, outcome, scope and project/change')
    if not acceptance or not specs or any(not isinstance(v, str) or not v for v in [*acceptance, *specs, *dependencies, *relationships]):
        raise ValueError('ticket needs acceptance and specification links')
    return '\n\n'.join([problem, 'Outcome: ' + outcome, 'Scope: ' + scope, 'Acceptance:\n' + '\n'.join('- ' + x for x in acceptance),
        f'OpenSpec: {project}/{change}\n' + '\n'.join(specs), 'Dependencies: ' + (', '.join(dependencies) or 'none'),
        'Related: ' + (', '.join(relationships) or 'none')])


def prepare_comment(event: str, decision: str, reason: str, consequence: str) -> str | None:
    if event not in EVENTS:
        return None
    if any(not isinstance(v, str) or not v.strip() for v in (decision, reason, consequence)):
        raise ValueError('material comment requires decision/evidence, reason and consequence')
    return f'{decision}\n\n{reason}\n\n{consequence}'


def markdown_headings(text: str):
    tokens = MarkdownIt().parse(text)
    return [(token.map[0], int(token.tag[1:]), tokens[index + 1].content)
            for index, token in enumerate(tokens)
            if token.type == 'heading_open' and token.level == 0]


def requirement_blocks(text: str) -> dict[str, str]:
    """Keep the complete normative body, not merely matching scenario titles."""
    blocks = {}
    lines, headings = text.splitlines(), markdown_headings(text)
    for index, (line, level, title) in enumerate(headings):
        if level != 3 or not title.startswith('Requirement: '):
            continue
        name = title.removeprefix('Requirement: ')
        end = next((position for position, depth, label in headings[index + 1:]
                    if depth <= 2 or (depth == 3 and label.startswith('Requirement: '))), len(lines))
        body = '\n'.join(lines[line + 1:end])
        if name in blocks:
            raise ValueError('duplicate normative requirement')
        blocks[name] = '\n'.join(line.rstrip() for line in body.strip().splitlines())
    return blocks


def synchronized_delta(delta: str, baseline: str) -> None:
    current = requirement_blocks(baseline)
    lines = delta.splitlines()
    sections = [(line, title) for line, level, title in markdown_headings(delta) if level == 2]
    for index, (start, title) in enumerate(sections):
        end = sections[index + 1][0] if index + 1 < len(sections) else len(lines)
        section = '\n'.join(lines[start + 1:end])
        if title in ('ADDED Requirements', 'MODIFIED Requirements'):
            expected = requirement_blocks(section)
            if not expected or any(current.get(name) != body for name, body in expected.items()):
                raise ValueError('synchronized capability differs from complete requirement bodies')
        elif title == 'REMOVED Requirements':
            if set(requirement_blocks(section)) & set(current):
                raise ValueError('removed requirement remains in synchronized capability')
        elif title == 'RENAMED Requirements':
            pairs = re.findall(r'(?m)^- FROM: `### Requirement: (.+)`\s*\n- TO: `### Requirement: (.+)`', section)
            if not pairs or any(old in current or new not in current for old, new in pairs):
                raise ValueError('renamed requirement differs from synchronized capability')


def acceptance_gate(request: dict) -> dict:
    """Verify original files and final content, not caller-provided ready booleans."""
    root = Path(request['worktree']).resolve()
    manifest = evidence.verify(Path(request['bundle']), root)
    if manifest['schema_version'] != 3:
        raise ValueError('new-plan acceptance requires mode-aware retained source')
    selected = projects.resolve(request['project'], root)
    change = request['change']
    if manifest['project'] != selected['id'] or manifest['change'] != change:
        raise ValueError('acceptance scope mismatch')
    archive = root / selected['root'] / 'openspec/changes/archive'
    matches = list(archive.glob('*-' + change))
    if len(matches) != 1 or (root / selected['root'] / 'openspec/changes' / change).exists():
        raise ValueError('same-PR specification lifecycle is incomplete')
    tasks = (matches[0] / 'tasks.md').read_text()
    if not re.search(r'- \[x\]', tasks, re.I) or re.search(r'- \[ \]', tasks):
        raise ValueError('unverified lifecycle tasks remain')
    deltas = list((matches[0] / 'specs').glob('*/spec.md'))
    skipped = intake.skips_specs(matches[0])
    if skipped and deltas:
        raise ValueError('skip_specs contradicts archived capability deltas')
    if not skipped and not deltas:
        raise ValueError('archived capability evidence is missing')
    required_source = {selected['queue'], '_agentic_harness/projects.yaml',
                       projects.config_path(root, selected).relative_to(root).as_posix()}
    required_source.update(p.relative_to(root).as_posix() for p in matches[0].rglob('*') if p.is_file())
    for delta in deltas:
        baseline = root / selected['root'] / 'openspec/specs' / delta.parent.name / 'spec.md'
        if not baseline.is_file():
            raise ValueError('implemented capability was not synchronized')
        required_source.add(baseline.relative_to(root).as_posix())
        synchronized_delta(delta.read_text(), baseline.read_text())
    changed = evidence.changed_scope(root, manifest['base_commit'])
    main_specs = Path(selected['root']) / 'openspec/specs'
    if skipped and any(Path(path).is_relative_to(main_specs)
                       for path in [*changed['input_scope'], *changed['deleted_scope']]):
        raise ValueError('skip_specs must leave implemented capability specifications unchanged')
    required_source.update(changed['input_scope'])
    if not required_source <= set(manifest['input_scope']) or not set(changed['deleted_scope']) <= set(manifest.get('deleted_files', {})):
        raise ValueError('final review scope omits changed source or lifecycle/check authority')
    required = {canonical(cmd) for cmd in selected['checks']}
    covered = set()
    for ref in request['checks']:
        raw = original(ref, root)
        check = json.loads(raw)
        if check.get('exit_code') != 0 or check.get('input_revision') != manifest['input_revision'] or check.get('head') != manifest['input_head']:
            raise ValueError('failed or stale required check')
        covered.add(canonical(check['command']))
    if not required <= covered:
        raise ValueError('required checks missing')
    from plan_runtime import Ledger
    ledger = Ledger(Path(request['ledger']))
    run = ledger.status(manifest['run_id'])
    if set(request['originals']) != set(run['launches']):
        raise ValueError('original evidence missing for launched attempts')
    identities = set()
    for launch_id, launch in run['launches'].items():
        refs = request['originals'][launch_id]
        if set(refs) != {'prompt', 'result', 'invocation', 'stdout', 'stderr'}:
            raise ValueError('incomplete original launch artifacts')
        payloads = {kind: original(ref, root) for kind, ref in refs.items()}
        if json.loads(payloads['result']) != launch['result'] or not payloads['prompt']:
            raise ValueError('original result/assignment differs from ledger')
        invocation = json.loads(payloads['invocation'])
        invoked = invocation.get('launch') if isinstance(invocation, dict) else None
        if not isinstance(invoked, dict) or any(invoked.get(key) != launch[key] for key in ('launch_id', 'identity', 'provider', 'input_revision', 'effective')):
            raise ValueError('original invocation differs from accepted assignment')
        paths = {str(Path(ref['path']).resolve()) for ref in refs.values()}
        if len(paths) != len(refs) or identities & paths:
            raise ValueError('original evidence reused across assignments')
        identities.update(paths)
    design = evidence.verify(Path(request['design_bundle']), root, current_head_required=False)
    required_design = {p.relative_to(root).as_posix() for p in deltas}
    required_design.update((matches[0] / name).relative_to(root).as_posix() for name in ('proposal.md', 'design.md'))
    metadata = matches[0] / '.openspec.yaml'
    if metadata.is_file():
        required_design.add(metadata.relative_to(root).as_posix())
    if design['schema_version'] != 3 or not required_design <= set(design['input_scope']):
        raise ValueError('design acceptance omits final design or capability contracts')
    if (design['project'], design['change'], design['run_id']) != (manifest['project'], manifest['change'], manifest['run_id']):
        raise ValueError('design acceptance scope mismatch')
    for phase in ('D', 'I'):
        # Engine enforces two independent identities and plan-specific clean minima.
        verdict = ledger.apply('gate', {'run_id': manifest['run_id'], 'phase': phase,
            'input_revision': design['input_revision'] if phase == 'D' else manifest['input_revision'], 'checks_passed': True})
        if not verdict['accepted']:
            raise ValueError(f'{phase} acceptance incomplete: {verdict["blockers"]}')
    return {'head': manifest['input_head'], 'revision': manifest['input_revision'], 'project': selected['id'],
            'change': change, 'status': 'verified',
            'specification_mode': 'unchanged' if skipped else 'synchronized'}


class Journal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, payload TEXT NOT NULL, hash TEXT NOT NULL, state TEXT NOT NULL, result TEXT, authority TEXT NOT NULL)')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def get(self, operation_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM operations WHERE id=?', (operation_id,)).fetchone()
        if row is None:
            raise ValueError('unknown operation')
        return {**dict(row), 'payload': json.loads(row['payload']), 'authority': json.loads(row['authority']), 'result': json.loads(row['result']) if row['result'] else None}

    def prepare(self, operation_id: str, payload: dict, authority: dict):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', operation_id) or payload.get('action') not in ACTIONS:
            raise ValueError('invalid operation identity/action')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', payload.get('repo', '')):
            raise ValueError('invalid repository')
        if not all(isinstance(payload.get(k), str) and payload[k] for k in ('project', 'change')):
            raise ValueError('operation needs project/change scope')
        action = payload['action']
        if action in {'issue', 'pr', 'edit-issue', 'edit-pr', 'comment'}:
            required = ['body'] + ([] if action == 'comment' else ['title'])
            if any(not isinstance(payload.get(k), str) or not payload[k].strip() for k in required):
                raise ValueError('prepare complete remote content before publication')
        if action in {'comment', 'edit-issue', 'edit-pr', 'ready', 'merge'} and (type(payload.get('number')) is not int or payload['number'] <= 0):
            raise ValueError('positive target number required')
        if action in {'push', 'ready', 'merge'} and not re.fullmatch(r'(?:[a-f0-9]{40}|[a-f0-9]{64})', payload.get('head', '')):
            raise ValueError('remote operation requires a pinned full head')
        for key in ('branch', 'base'):
            if key in payload and (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', payload[key]) or '..' in payload[key] or payload[key].endswith('/')):
                raise ValueError('unsafe remote branch/base')
        if 'remote' in payload and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', payload['remote']):
            raise ValueError('remote must be a configured remote name')
        encoded, fingerprint = canonical(payload), digest(payload)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT hash FROM operations WHERE id=?', (operation_id,)).fetchone()
            if old and old['hash'] != fingerprint:
                raise ValueError('operation payload changed; reconcile original then use a new intentional operation')
            if not old:
                db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?)', (operation_id, encoded, fingerprint, 'prepared', None, canonical(authority)))
        return self.get(operation_id)

    def grant(self, operation_id, authority):
        item = self.get(operation_id)
        p = item['payload']
        if not permitted(authority, p['action'], p['project'], p['change']):
            raise ValueError('authority does not cover this operation')
        with self.connect() as db:
            db.execute('UPDATE operations SET authority=? WHERE id=?', (canonical(authority), operation_id))
        return self.get(operation_id)

    def reconcile(self, operation_id, remote):
        item = self.get(operation_id)
        if item['state'] == 'observed':
            return item
        observed = remote.find(item)
        if observed is not None:
            with self.connect() as db:
                db.execute('UPDATE operations SET state=?,result=? WHERE id=?', ('observed', canonical(observed), operation_id))
        return self.get(operation_id)

    def execute(self, operation_id, remote):
        item = self.reconcile(operation_id, remote)
        if item['state'] != 'prepared':
            return item  # unknown/sending stays unresolved; never a blind second mutation
        p = item['payload']
        if not permitted(item['authority'], p['action'], p['project'], p['change']):
            return {**item, 'blocked': 'missing scoped action authority; prepared content retained'}
        if p['action'] in {'ready', 'merge'}:
            gate = acceptance_gate(p['gate'])
            if gate['head'] != p['head'] or (gate['project'], gate['change']) != (p['project'], p['change']):
                raise ValueError('remote transition head differs from accepted content')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE operations SET state='sending' WHERE id=? AND state='prepared'", (operation_id,)).rowcount
        if not changed:
            return self.get(operation_id)
        try:
            remote.perform(item)
        except Exception as exc:
            with self.connect() as db:
                db.execute('UPDATE operations SET state=?,result=? WHERE id=?', ('unknown', canonical({'error_type': type(exc).__name__}), operation_id))
            return self.get(operation_id)
        # A command exit status is not a verified remote result.
        with self.connect() as db:
            db.execute("UPDATE operations SET state='unknown' WHERE id=?", (operation_id,))
        return self.reconcile(operation_id, remote)


class GhRemote:
    def __init__(self, worktree: Path):
        self.worktree = Path(worktree)

    def run(self, args):
        result = subprocess.run(args, cwd=self.worktree, check=True, text=True, capture_output=True)
        return result.stdout.strip()

    def api(self, endpoint):
        output = self.run(['gh', 'api', '--paginate', '--slurp', endpoint])
        pages = json.loads(output)
        return [item for page in pages for item in (page if isinstance(page, list) else [page])]

    @staticmethod
    def marker(item):
        return f'<!-- sdw-operation:{item["id"]}:{item["hash"]} -->'

    def find(self, item):
        p, action = item['payload'], item['payload']['action']
        repo = p['repo']
        if action in {'issue', 'pr', 'comment', 'edit-issue', 'edit-pr'}:
            if action == 'comment':
                endpoint = f'repos/{repo}/issues/{int(p["number"])}/comments?per_page=100'
            elif action in {'edit-issue', 'edit-pr'}:
                endpoint = f'repos/{repo}/issues/{int(p["number"])}'
            else:
                endpoint = f'repos/{repo}/issues?state=all&per_page=100'
            matches = [r for r in self.api(endpoint) if self.marker(item) in (r.get('body') or '')]
            if len(matches) > 1:
                raise ValueError('multiple remote operation matches; manual reconciliation required')
            if matches:
                r = matches[0]
                return {'id': r['id'], 'url': r['html_url'], 'number': r.get('number'), 'observed': True}
            if action == 'pr':
                pulls = self.api(f'repos/{repo}/pulls?state=open&head={repo.split("/")[0]}:{p["branch"]}&per_page=100')
                if pulls:
                    # Do not silently duplicate/rewrite another scope's PR.
                    raise ValueError(f'existing branch PR must be explicitly selected: {pulls[0]["html_url"]}')
            return None
        if action == 'push':
            current = self.run(['git', 'ls-remote', p.get('remote', 'origin'), 'refs/heads/' + p['branch']]).split()
            if current and current[0] == p['head']:
                return {'branch': p['branch'], 'head': p['head'], 'observed': True}
            if current and current[0] != p.get('previous_head'):
                raise ValueError('remote branch changed; reconcile before pushing')
            return None
        record = self.api(f'repos/{repo}/pulls/{int(p["number"])}')[0]
        if record['head']['sha'] != p['head'] or record['base']['ref'] != p['base']:
            raise ValueError('PR head/base changed since verification')
        if (action == 'ready' and record['draft'] is False) or (action == 'merge' and record.get('merged') is True):
            return {'id': record['id'], 'url': record['html_url'], 'head': p['head'], 'merged': record.get('merged', False), 'observed': True}
        return None

    def perform(self, item):
        p, action = item['payload'], item['payload']['action']
        repo = p['repo']
        if action == 'push':
            head = self.run(['git', 'rev-parse', p['branch']])
            if head != p['head']:
                raise ValueError('local branch head changed')
            self.run(['git', 'push', p.get('remote', 'origin'), p['head'] + ':refs/heads/' + p['branch']])
            return
        if action in {'ready', 'merge'}:
            self.find(item)  # current remote head/base recheck immediately before mutation
            if action == 'merge':
                self.run(['gh', 'pr', 'checks', str(p['number']), '--repo', repo, '--required'])
                self.run(['gh', 'pr', 'merge', str(p['number']), '--repo', repo, '--squash', '--match-head-commit', p['head']])
            else:
                self.run(['gh', 'pr', 'ready', str(p['number']), '--repo', repo])
            return
        with tempfile.TemporaryDirectory(prefix='harness-github-') as tmp:
            body = Path(tmp) / 'body.md'
            body.write_text(p['body'] + '\n\n' + self.marker(item) + '\n')
            if action == 'issue':
                args = ['gh', 'issue', 'create', '--title', p['title']]
            elif action == 'pr':
                args = ['gh', 'pr', 'create', '--draft', '--head', p['branch'], '--base', p['base'], '--title', p['title']]
            elif action == 'comment':
                args = ['gh', 'issue', 'comment', str(int(p['number']))]
            else:
                args = ['gh', 'pr' if action == 'edit-pr' else 'issue', 'edit', str(int(p['number'])), '--title', p['title']]
            self.run([*args, '--repo', repo, '--body-file', str(body)])
