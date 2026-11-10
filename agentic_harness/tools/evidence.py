"""Versioned retained source: schema 4 adds inert approved discovery link records.

Schemas 2 and 3 retain their original identity formulas and interpretation.
New runs materialize schema 4; callers gate policy/version compatibility.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

import yaml
import projects
import skill_links
from projects import relative_path, scope_contains

PRIVATE_PARTS = {'.git', '.env', 'node_modules', '.venv', '__pycache__'}
MODES = {'100644', '100755'}
TYPED_MODES = MODES | {'120000'}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def _mode(mode):
    return '100755' if mode & stat.S_IXUSR else '100644'


def _scope(scope, *, empty=False):
    if not isinstance(scope, list) or (not scope and not empty) or any(not isinstance(p, str) or not p for p in scope) or scope != sorted(set(scope)):
        raise ValueError('source scope must be nonempty, sorted, unique explicit files')


def _private(rel, exclusions=()):
    return (any(part.lower() in PRIVATE_PARTS or part.lower().startswith('.env.')
                or part.lower().endswith('.pem') for part in Path(rel).parts)
            or any(scope_contains(scope, rel) for scope in exclusions))


def _exclusions(root, project):
    """Dependency reads respect private paths declared by every registered domain."""
    if not any(os.path.lexists(root / name) for name in (projects.INDEX_PATH, projects.LEGACY_INDEX_PATH)):
        return []
    registered = projects.registry(root)
    if project not in registered:
        raise ValueError(f'unknown OpenSpec project: {project}')
    return sorted({path for selected in registered.values() for path in selected['evidence_exclude']})


def _base_exclusions(repository, base):
    """Use only immutable, schema-selected privacy authority, including old roots."""
    def present(relative):
        return bool(subprocess.check_output(['git', '--git-dir', str(repository), 'ls-tree', '-z', base, '--', relative]))

    indices = [name for name in (projects.INDEX_PATH, projects.LEGACY_INDEX_PATH) if present(name)]
    if len(indices) > 1:
        raise ValueError('ambiguous pinned-base privacy policy: both package directories contain projects.yaml')
    if not indices:
        return []
    index = indices[0]

    def read_policy(relative):
        try:
            record, content = _tree(repository, base, relative)
            if record['mode'] not in MODES:
                raise ValueError('policy must be a regular file')
            value = yaml.load(content, Loader=projects.UniqueLoader)
        except (ValueError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError(f'invalid pinned-base privacy policy: {relative}: {exc}') from exc
        if not isinstance(value, dict):
            raise ValueError(f'invalid pinned-base privacy policy: {relative}')
        return value

    def normalize(settings):
        settings = dict(settings)
        if not {'code_roots', 'checks'} <= set(settings) or set(settings) - {'code_roots', 'checks', 'environment', 'evidence_exclude'}:
            raise ValueError('invalid pinned-base workflow configuration')
        def paths(value, label, *, nonempty=False, allow_root=True):
            if (not isinstance(value, list) or (nonempty and not value) or any(not isinstance(p, str) for p in value)
                    or len(set(value)) != len(value)):
                raise ValueError(f'invalid pinned-base {label}')
            for path in value:
                scope_contains(path, path)
                if path == '.' and not allow_root:
                    raise ValueError(f'invalid pinned-base {label}')
            return value
        environment = settings.get('environment', {})
        if not isinstance(environment, dict) or set(environment) - {'lockfiles', 'prepare'}:
            raise ValueError('invalid pinned-base environment')
        return {'code_roots': paths(settings['code_roots'], 'code roots', nonempty=True),
                'checks': projects._argv_commands(settings['checks'], 'pinned-base checks'),
                'environment': {'lockfiles': paths(environment.get('lockfiles', []), 'lockfiles', allow_root=False),
                                'prepare': projects._argv_commands(environment.get('prepare', []), 'pinned-base preparation', empty=True)},
                'evidence_exclude': paths(settings.get('evidence_exclude', []), 'evidence exclusions')}

    def companion(relative):
        value = read_policy(relative)
        if type(value.get('schema_version')) is not int or value['schema_version'] != 1:
            raise ValueError(f'invalid pinned-base workflow configuration: {relative}')
        return normalize({k: v for k, v in value.items() if k != 'schema_version'})

    registered = read_policy(index)
    if (set(registered) != {'schema_version', 'projects'} or type(registered['schema_version']) is not int
            or registered['schema_version'] not in (1, 2, 3)
            or not isinstance(registered['projects'], dict) or not registered['projects']):
        raise ValueError('invalid pinned-base project registration')
    version, exclusions = registered['schema_version'], set()
    package_root = Path(index).parent
    for name, binding in registered['projects'].items():
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', name) or not isinstance(binding, dict):
            raise ValueError('invalid pinned-base project registration')
        if version >= 2:
            if set(binding) != {'root'}:
                raise ValueError('invalid pinned-base project index')
        elif not {'root', 'queue', 'code_roots', 'checks'} <= set(binding) or set(binding) - {'root', 'queue', 'code_roots', 'checks', 'environment', 'evidence_exclude'}:
            raise ValueError('invalid pinned-base project registration')
        home = binding['root']
        scope_contains(home, home)
        old = projects.workflow_path(home, 2)
        new = (package_root / 'config' / home / 'workflow.yaml').as_posix()
        alternate = old if version == 3 else new
        alternate_map = (Path(home) / ('openspec/queue.yaml' if version == 3 else 'openspec/dependency-map.yaml')).as_posix()
        if present(alternate) or present(alternate_map):
            raise ValueError('ambiguous pinned-base workflow authority')
        if version == 1:
            queue = binding['queue']
            scope_contains(queue, queue)
            if Path(queue).parent != Path(home) / 'openspec':
                raise ValueError('invalid pinned-base project queue')
            settings = normalize({k: v for k, v in binding.items() if k not in {'root', 'queue'}})
            if present(old) and companion(old) != settings:
                raise ValueError('conflicting pinned-base legacy and local workflow configuration')
        else:
            settings = companion(new if version == 3 else old)
        exclusions.update(settings['evidence_exclude'])
    return sorted(exclusions)


def _leaf_path(root, rel):
    # Only the finite discovery leaf may be a symlink. Every parent remains real.
    try:
        skill_links.expected_target(rel)
    except ValueError:
        return relative_path(root, rel)
    relative_path(root, str(Path(rel).parent), exists=True)
    path = root / rel
    if path.is_symlink():
        skill_links.validate_link(root, rel)
    return path


def _public(root, rel, *, exists=False, strict_ignored=True, exclusions=(), typed=False):
    path = _leaf_path(root, rel) if typed else relative_path(root, rel, exists=exists)
    if exists and not os.path.lexists(path):
        raise ValueError(f'missing registered path: {rel}')
    if _private(rel, exclusions):
        raise ValueError(f'private/runtime source is not review material: {rel}')
    ignore_args = ['--no-index'] if strict_ignored else []
    if subprocess.run(['git', '-C', str(root), 'check-ignore', *ignore_args, '-q', '--', rel]).returncode == 0:
        raise ValueError(f'ignored source must not enter review bundle: {rel}')
    return path


def _inventory(root, scope, *, empty=False, strict_ignored=True, exclusions=(), typed=False):
    _scope(scope, empty=empty)
    hashes, contents, modes = {}, {}, {}
    for rel in scope:
        path = _public(root, rel, exists=True, strict_ignored=strict_ignored, exclusions=exclusions, typed=typed)
        parent_state = _parents(root, rel)
        if typed and path.is_symlink():
            canonical = skill_links.canonical_skill(rel)
            if canonical not in scope:
                raise ValueError(f'link requires explicit canonical SKILL.md in input scope: {canonical}')
            before = path.lstat()
            data = os.readlink(path).encode('utf-8')
            skill_links.validate_link(root, rel)
            if _identity(before) != _identity(path.lstat()) or parent_state != _parents(root, rel):
                raise ValueError(f'source changed during capture: {rel}')
            contents[rel], hashes[rel], modes[rel] = data, _hash(data), '120000'
            continue
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f'non-regular review source: {rel}')
            data = stream.read()
            after = os.fstat(stream.fileno())
            current = path.stat(follow_symlinks=False)
        if (_identity(before) != _identity(after) or _identity(current) != _identity(before)
                or parent_state != _parents(root, rel)):
            raise ValueError(f'source changed during capture: {rel}')
        contents[rel] = data
        hashes[rel] = _hash(data)
        modes[rel] = _mode(before.st_mode)
    return hashes, contents, modes


def _identity(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)


def _parents(root, rel):
    paths = [root, *[root.joinpath(*Path(rel).parts[:n]) for n in range(1, len(Path(rel).parts))]]
    result = []
    for path in paths:
        state = path.lstat()
        if not stat.S_ISDIR(state.st_mode):
            raise ValueError(f'aliased source parent: {rel}')
        result.append(_identity(state))
    return result


def inventory(root: Path, scope: list[str]) -> tuple[dict, dict]:
    """Compatibility view; mode-aware materialization uses the full inventory."""
    hashes, contents, _ = _inventory(root, scope)
    return hashes, contents


def revision(files, modes, deleted, schema_version=3):
    """Canonical schema-3 identity; modes and deleted originals are relevant bytes."""
    payload = {'input_files': files, 'input_modes': modes, 'deleted_files': deleted}
    if schema_version == 4:
        payload['schema_version'] = 4
    return _hash(json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def _tree(repository, base, rel):
    if not isinstance(base, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', base):
        raise ValueError('deleted source requires an immutable base commit')
    scope_contains(rel, rel)
    if rel == '.':
        raise ValueError('review source must be an explicit leaf')
    output = subprocess.check_output(['git', '--git-dir', str(repository), 'ls-tree', '-z', base, '--', rel])
    if subprocess.check_output(['git', '--git-dir', str(repository), 'cat-file', '-t', base], text=True).strip() != 'commit':
        raise ValueError('deleted source base is not a commit object')
    records = [r for r in output.split(b'\0') if r]
    if len(records) != 1:
        raise ValueError(f'deleted source absent from pinned base: {rel}')
    header, filename = records[0].split(b'\t', 1)
    mode, kind, oid = header.decode().split()
    if filename.decode() != rel or kind != 'blob' or mode not in TYPED_MODES:
        raise ValueError(f'deleted symlink/non-regular source is forbidden: {rel}')
    # Validate each immutable ancestor too: Git pathspec lookup must not grant aliases.
    for n in range(1, len(Path(rel).parts)):
        ancestor = '/'.join(Path(rel).parts[:n])
        entry = subprocess.check_output(['git', '--git-dir', str(repository), 'ls-tree', '-z', base, '--', ancestor])
        if not entry.startswith(b'040000 tree '):
            raise ValueError(f'aliased pinned-base ancestor: {rel}')
    content = subprocess.check_output(['git', '--git-dir', str(repository), 'cat-file', 'blob', oid])
    if mode == '120000':
        try:
            expected = skill_links.expected_target(rel).encode('utf-8')
        except ValueError as exc:
            raise ValueError(f'deleted symlink/non-regular source is forbidden: {rel}') from exc
        if content != expected:
            raise ValueError(f'unsafe deleted discovery link: {rel}')
    return {'sha256': _hash(content), 'mode': mode}, content


def _lexical_exists(root, rel):
    scope_contains(rel, rel)
    current = root
    for part in Path(rel).parts[:-1]:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            return False
    return os.path.lexists(root / rel)


def _deleted_ignored(root, rel):
    """Ask Git about displaced paths without traversing their new link parent."""
    result = subprocess.run(['git', '-C', str(root), 'check-ignore', '--no-index', '-q', '--', rel],
                            capture_output=True)
    if result.returncode in (0, 1):
        return result.returncode == 0
    # Git refuses a pathspec below a symlink. Reproduce its ignore context in
    # an inert tree, using this repository's config and info/exclude as usual.
    repository = _git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    with tempfile.TemporaryDirectory(prefix='deleted-ignore-') as directory:
        scratch = Path(directory)
        for n in range(len(Path(rel).parts)):
            parent = Path(*Path(rel).parts[:n])
            if n and (root / parent).is_symlink():
                break
            if n and not (root / parent).is_dir():
                break
            ignore = root / parent / '.gitignore'
            if ignore.is_file() and not ignore.is_symlink():
                destination = scratch / parent / '.gitignore'
                destination.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(ignore, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as stream:
                    before = os.fstat(stream.fileno())
                    data = stream.read()
                    if _identity(before) != _identity(os.fstat(stream.fileno())) or _identity(before) != _identity(ignore.lstat()):
                        raise ValueError('ignore policy changed during capture')
                destination.write_bytes(data)
        options = []
        configured = subprocess.run(['git', '-C', str(root), 'config', '--path', '--get', 'core.excludesFile'],
                                    text=True, capture_output=True)
        if configured.returncode not in (0, 1):
            raise ValueError('cannot validate configured source ignore policy')
        if configured.returncode == 0:
            exclude_file = Path(configured.stdout.rstrip('\n'))
            if not exclude_file.is_absolute():
                exclude_file = root / exclude_file
            options = ['-c', 'core.excludesFile=' + str(exclude_file)]
        result = subprocess.run(['git', '-C', str(scratch), '--git-dir', repository, '--work-tree', str(scratch),
                                 *options, 'check-ignore', '--no-index', '-q', '--', rel], capture_output=True)
        if result.returncode not in (0, 1):
            raise ValueError(f'cannot validate deleted source ignore policy: {rel}')
        return result.returncode == 0


def _deleted(root, repository, base, scope, *, exclusions=()):
    _scope(scope, empty=True)
    records, contents = {}, {}
    for rel in scope:
        scope_contains(rel, rel)
        if _private(rel, exclusions):
            raise ValueError(f'private/runtime source is not review material: {rel}')
        if _deleted_ignored(root, rel):
            raise ValueError(f'ignored source must not enter review bundle: {rel}')
        if _lexical_exists(root, rel):
            raise ValueError(f'deleted source was recreated or still exists: {rel}')
        records[rel], contents[rel] = _tree(repository, base, rel)
    return records, contents


def _reject_replacements(root, repository, base, scope):
    for rel in scope:
        output = subprocess.check_output(['git', '--git-dir', str(repository), 'ls-tree', '-z', base, '--', rel])
        if not output:
            continue
        old_mode = output.split(b' ', 1)[0].decode()
        new_link = (root / rel).is_symlink()
        if (old_mode == '120000' and not new_link) or (old_mode in MODES and new_link):
            raise ValueError(f'unsupported same-leaf regular-file/link type transition: {rel}')


def changed_scope(root: Path, base: str) -> dict:
    """Complete current new/changed/deleted file scope against pinned Git base.

    Mode comparisons are explicit even with core.filemode=false. Rename pairs
    remain a deletion and addition, retaining the original contract/source.
    """
    root = Path(root).resolve()
    base = _git(root, 'rev-parse', '--verify', base + '^{commit}')
    tree = subprocess.check_output(['git', '-C', str(root), 'ls-tree', '-rz', '--full-tree', base])
    originals = {}
    for record in tree.split(b'\0'):
        if record:
            header, rel = record.split(b'\t', 1)
            originals[rel.decode()] = header.decode().split()[0]
    changed = set(filter(None, subprocess.check_output(['git', '-C', str(root), 'diff', '--name-only', '-z', '--no-renames', base, '--']).decode().split('\0')))
    tracked_and_new = set(filter(None, subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard']).decode().split('\0')))
    changed.update(tracked_and_new - originals.keys())
    deleted = []
    for rel, mode in originals.items():
        path = root / rel
        if not _lexical_exists(root, rel):
            deleted.append(rel)
        elif path.is_symlink():
            if mode != '120000': changed.add(rel)
        elif mode in MODES and (not path.is_file() or _mode(path.stat().st_mode) != mode):
            changed.add(rel)
        elif mode not in MODES and mode != '160000':
            changed.add(rel)
    current = sorted(p for p in changed if _lexical_exists(root, p))
    repository = _git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    _reject_replacements(root, repository, base, current)
    for rel in current:
        _leaf_path(root, rel)
    for rel in deleted:
        if originals[rel] == '120000':
            _tree(repository, base, rel)
    return {'input_scope': current, 'deleted_scope': sorted(deleted)}


def _capture_states(root, scope):
    """Keep no-follow identities across the complete capture, not just each read."""
    result = {}
    for rel in scope:
        try:
            path = _leaf_path(root, rel)
            result[rel] = (_parents(root, rel), _identity(path.lstat()))
        except OSError as exc:
            raise ValueError(f'missing registered path or changed source: {rel}') from exc
    return result


def _deleted_states(root, scope):
    """Record absence and real ancestors, stopping at displaced link parents.

    Directory descriptors keep a concurrent parent swap from redirecting the
    observation. A link is inert state here; deleted-original reads use Git.
    """
    result = {}
    for rel in scope:
        scope_contains(rel, rel)
        states = []
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            states.append(_identity(os.fstat(fd)))
            parts = Path(rel).parts
            for index, part in enumerate(parts):
                try:
                    info = os.stat(part, dir_fd=fd, follow_symlinks=False)
                except FileNotFoundError:
                    states.append(None)
                    break
                states.append(_identity(info))
                if index == len(parts) - 1 or not stat.S_ISDIR(info.st_mode):
                    break
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                if _identity(os.fstat(child)) != _identity(info):
                    os.close(child)
                    raise ValueError(f'deleted source parent changed during verification: {rel}')
                os.close(fd)
                fd = child
        finally:
            os.close(fd)
        result[rel] = states
    return result


def _policy_states(root):
    if not os.path.lexists(root / projects.INDEX_PATH):
        return {}
    paths = {projects.INDEX_PATH}
    for name, binding in projects.registry(root).items():
        selected = {'id': name, **binding}
        paths.update(projects.configuration_paths(root, selected))
        paths.add(binding['queue'])
        paths.add(projects.config_path(root, selected).relative_to(root).as_posix())
        # Legacy inline settings may have an agreeing optional companion.
        old = projects.workflow_path(binding['root'], 2)
        if os.path.lexists(root / old):
            paths.add(old)
    return {rel: (_parents(root, rel), _identity(relative_path(root, rel, exists=True).lstat())) for rel in sorted(paths)}


def materialize(worktree: Path, destination: Path, scope: list[str], *, project: str, change: str, run_id: str,
                base: str, policy: str, deleted_scope: list[str] | None = None) -> dict:
    worktree, destination = worktree.resolve(), destination.absolute()
    if destination.exists() or destination.resolve().is_relative_to(worktree) or destination.parent.is_symlink():
        raise ValueError('bundle requires a fresh external destination')
    if not all(isinstance(v, str) and v for v in (project, change, run_id, base, policy)):
        raise ValueError('bundle identity is incomplete')
    deleted_scope = [] if deleted_scope is None else deleted_scope
    _scope(scope, empty=True); _scope(deleted_scope, empty=True)
    if not scope and not deleted_scope or set(scope) & set(deleted_scope):
        raise ValueError('source scope must be nonempty and disjoint from deleted scope')
    head = _git(worktree, 'rev-parse', 'HEAD')
    base = _git(worktree, 'rev-parse', '--verify', base + '^{commit}')
    common = str(Path(_git(worktree, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve())
    policy_states = _policy_states(worktree)
    exclusions = _exclusions(worktree, project)
    source_states = _capture_states(worktree, scope)
    deleted_exclusions = sorted(set(exclusions) | set(_base_exclusions(common, base))) if deleted_scope else exclusions
    files, contents, modes = _inventory(worktree, scope, empty=True, exclusions=exclusions, typed=True)
    _reject_replacements(worktree, common, base, scope)
    deleted, deleted_contents = _deleted(worktree, common, base, deleted_scope, exclusions=deleted_exclusions)
    manifest = dict(schema_version=4, kind='retained-review-source', project=project, change=change, run_id=run_id,
                    policy=policy, repository=common, input_head=head, base_commit=base, input_scope=scope,
                    input_files=files, input_modes=modes, deleted_files=deleted, input_revision=revision(files, modes, deleted, 4),
                    evidence_exclude=exclusions, deleted_evidence_exclude=deleted_exclusions)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.capture-', dir=destination.parent) as temp:
        tmp = Path(temp)
        for folder, data_map, mode_map in [('source', contents, modes), ('deleted-source', deleted_contents, {p: d['mode'] for p, d in deleted.items()})]:
            (tmp / folder).mkdir()
            for rel, data in data_map.items():
                path = tmp / folder / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                path.chmod(0o555 if mode_map[rel] == '100755' else 0o444)
        (tmp / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        again, _, again_modes = _inventory(worktree, scope, empty=True, exclusions=exclusions, typed=True)
        again_deleted, _ = _deleted(worktree, common, base, deleted_scope, exclusions=deleted_exclusions)
        if _policy_states(worktree) != policy_states or _exclusions(worktree, project) != exclusions:
            raise ValueError('evidence policy changed during materialization; no bundle published')
        if (_capture_states(worktree, scope) != source_states
                or (again, again_modes, again_deleted) != (files, modes, deleted)
                or _git(worktree, 'rev-parse', 'HEAD') != head):
            raise ValueError('source changed during materialization; no bundle published')
        destination.mkdir()
        for item in tmp.iterdir():
            item.rename(destination / item.name)
    for path in sorted(destination.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir(): path.chmod(0o555)
        elif path.name == 'manifest.json' and path.parent == destination: path.chmod(0o444)
    destination.chmod(0o555)
    return manifest


def _retained(bundle, folder, files, modes=None, *, public=False, exclusions=(), strict_entries=False):
    base = bundle / folder
    if base.is_symlink() or ((files or strict_entries) and not base.is_dir()):
        raise ValueError(f'retained {folder} inventory mismatch')
    entries = list(base.rglob('*'))
    expected_entries = set(files)
    for rel in files:
        expected_entries.update(parent.as_posix() for parent in Path(rel).parents if parent != Path('.'))
    actual_entries = {p.relative_to(base).as_posix() for p in entries}
    if strict_entries and (any(p.is_symlink() for p in entries) or actual_entries != expected_entries):
        raise ValueError(f'retained {folder} inventory mismatch')
    actual = sorted(p.relative_to(base).as_posix() for p in entries if p.is_file())
    if actual != sorted(files):
        raise ValueError(f'retained {folder} inventory mismatch')
    for rel, expected in files.items():
        if public and _private(rel, exclusions):
            raise ValueError(f'private/runtime source is not review material: {rel}')
        path = relative_path(base, rel, exists=True)
        if not path.is_file() or _hash(path.read_bytes()) != expected:
            raise ValueError(f'retained source changed: {rel}')
        if modes is not None and _mode(path.stat().st_mode) != ('100644' if modes[rel] == '120000' else modes[rel]):
            raise ValueError(f'retained source mode changed: {rel}')
        if modes is not None and modes[rel] == '120000' and path.stat().st_mode & 0o222:
            raise ValueError(f'retained link data must be read-only: {rel}')


def verify(bundle: Path, worktree: Path | None = None, *, current_head_required: bool = True) -> dict:
    bundle = Path(bundle)
    manifest = json.loads((bundle / 'manifest.json').read_text())
    version = manifest.get('schema_version')
    if version not in (2, 3, 4) or manifest.get('kind') != 'retained-review-source':
        raise ValueError('unsupported retained-source manifest')
    files = manifest['input_files']
    if not isinstance(files, dict) or sorted(files) != manifest['input_scope']:
        raise ValueError('retained scope differs from inventory')
    if version == 2:
        if not files or _hash(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()) != manifest['input_revision']:
            raise ValueError('retained revision mismatch')
        _retained(bundle, 'source', files)
    else:
        exclusions = manifest.get('evidence_exclude', [])
        if not isinstance(exclusions, list) or any(not isinstance(p, str) for p in exclusions) or len(set(exclusions)) != len(exclusions):
            raise ValueError('invalid retained evidence exclusions')
        for excluded in exclusions:
            projects.relative_root(bundle / 'source', excluded)
        modes, deleted = manifest['input_modes'], manifest['deleted_files']
        if not isinstance(modes, dict) or modes.keys() != files.keys() or any(not isinstance(m, str) or m not in (TYPED_MODES if version == 4 else MODES) for m in modes.values()) or not isinstance(deleted, dict) or set(files) & set(deleted) or not (files or deleted):
            raise ValueError('invalid retained source modes/deletions')
        for rel, entry in deleted.items():
            if not isinstance(entry, dict) or set(entry) != {'sha256', 'mode'} or not isinstance(entry['mode'], str) or entry['mode'] not in (TYPED_MODES if version == 4 else MODES):
                raise ValueError('invalid deleted source identity')
        declared_deleted_exclusions = manifest.get('deleted_evidence_exclude', exclusions)
        if not isinstance(declared_deleted_exclusions, list):
            raise ValueError('invalid deleted evidence exclusions')
        for excluded in declared_deleted_exclusions:
            scope_contains(excluded, excluded)
        deleted_exclusions = sorted(set(exclusions) | set(declared_deleted_exclusions)
                                    | (set(_base_exclusions(manifest['repository'], manifest['base_commit'])) if deleted else set()))
        if revision(files, modes, deleted, version) != manifest['input_revision']:
            raise ValueError('retained revision mismatch')
        if version == 4:
            for rel, mode in modes.items():
                if mode == '120000':
                    if modes.get(skill_links.canonical_skill(rel)) not in MODES:
                        raise ValueError('link requires explicit canonical SKILL.md coverage')
                    link_data = relative_path(bundle / 'source', rel, exists=True).read_bytes()
                    if link_data != skill_links.expected_target(rel).encode('utf-8'):
                        raise ValueError('retained discovery link target changed')
        _retained(bundle, 'source', files, modes, public=True, exclusions=exclusions, strict_entries=version == 4)
        _retained(bundle, 'deleted-source', {p: d['sha256'] for p, d in deleted.items()}, {p: d['mode'] for p, d in deleted.items()}, public=True, exclusions=deleted_exclusions, strict_entries=version == 4)
        for rel, expected in deleted.items():
            # Both public-path checks and the pinned base blob apply even when
            # the caller verifies retained evidence without a live worktree.
            relative_path(bundle / 'deleted-source', rel, exists=True)
            if _private(rel, deleted_exclusions):
                raise ValueError('private deleted source is forbidden')
            original, _ = _tree(manifest['repository'], manifest['base_commit'], rel)
            if original != expected:
                raise ValueError(f'deleted source differs from pinned base: {rel}')
    if worktree is not None:
        worktree = Path(worktree)
        if str(Path(_git(worktree, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()) != manifest['repository']:
            raise ValueError('repository identity mismatch')
        live_head = _git(worktree, 'rev-parse', 'HEAD')
        if current_head_required and live_head != manifest['input_head']:
            raise ValueError('current final bytes differ from reviewed source')
        source_states = _capture_states(worktree, manifest['input_scope'])
        deleted_states = _deleted_states(worktree, sorted(manifest['deleted_files'])) if version >= 3 else {}
        policy_states = _policy_states(worktree) if version >= 3 else {}
        live_exclusions = _exclusions(worktree, manifest['project']) if version >= 3 else []
        current, _, current_modes = _inventory(worktree, manifest['input_scope'], empty=version >= 3,
                                               strict_ignored=version >= 3, exclusions=live_exclusions, typed=version == 4)
        if current != files or (version >= 3 and current_modes != manifest['input_modes']):
            raise ValueError('current final bytes/modes differ from reviewed source')
        if version >= 3:
            _deleted(worktree, manifest['repository'], manifest['base_commit'], sorted(manifest['deleted_files']),
                     exclusions=sorted(set(live_exclusions) | set(deleted_exclusions)))
        if version >= 3 and (_policy_states(worktree) != policy_states
                             or _exclusions(worktree, manifest['project']) != live_exclusions):
            raise ValueError('evidence policy changed during verification')
        if (_capture_states(worktree, manifest['input_scope']) != source_states
                or (version >= 3 and _deleted_states(worktree, sorted(manifest['deleted_files'])) != deleted_states)
                or _git(worktree, 'rev-parse', 'HEAD') != live_head
                or str(Path(_git(worktree, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()) != manifest['repository']):
            raise ValueError('source changed during verification')
    return manifest
