"""Versioned retained source: schema 3 binds bytes, Git modes and deletions.

Schema 2 is verified with its original hash-only semantics, never relabelled.
New runs materialize schema 3; callers gate policy/version compatibility.
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
from projects import relative_path, scope_contains

PRIVATE_PARTS = {'.git', '.env', 'node_modules', '.venv', '__pycache__'}
MODES = {'100644', '100755'}


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
    """Deleted originals retain the privacy policy of their immutable Git base."""
    # Resolve authority within the immutable commit, never by live-layout or
    # preferred-name fallback. Two indices can carry conflicting exclusions.
    present = [name for name in (projects.INDEX_PATH, projects.LEGACY_INDEX_PATH)
               if subprocess.check_output(['git', '--git-dir', str(repository), 'ls-tree', '-z', base, '--', name])]
    if len(present) > 1:
        raise ValueError('ambiguous pinned-base privacy policy: both package directories contain projects.yaml')
    if not present:
        return []
    config = present[0]

    def read_policy(relative):
        # Both the index and its referenced files belong to this immutable
        # commit. The live checkout may have moved or removed the exclusion.
        try:
            _, content = _tree(repository, base, relative)
            value = yaml.load(content, Loader=projects.UniqueLoader)
        except (ValueError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError(f'invalid pinned-base privacy policy: {relative}: {exc}') from exc
        if not isinstance(value, dict):
            raise ValueError(f'invalid pinned-base privacy policy: {relative}')
        return value

    registered = read_policy(config)
    if (set(registered) != {'schema_version', 'projects'}
            or type(registered['schema_version']) is not int
            or registered['schema_version'] not in (1, 2)
            or not isinstance(registered['projects'], dict) or not registered['projects']):
        raise ValueError('invalid pinned-base project registration')
    exclusions = set()
    for name, selected in registered['projects'].items():
        if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', name)
                or not isinstance(selected, dict)):
            raise ValueError('invalid pinned-base project registration')
        if registered['schema_version'] == 2:
            if set(selected) != {'root'}:
                raise ValueError('invalid pinned-base project index')
            project_root = selected['root']
            scope_contains(project_root, project_root)  # No reads from the live filesystem.
            companion = (Path(project_root) / 'openspec/workflow.yaml').as_posix()
            selected = read_policy(companion)
            required = {'schema_version', 'code_roots', 'checks'}
            optional = {'environment', 'evidence_exclude'}
            if (not required <= set(selected) or set(selected) - required - optional
                    or type(selected.get('schema_version')) is not int
                    or selected['schema_version'] != 1):
                raise ValueError(f'invalid pinned-base workflow configuration: {companion}')
        else:
            required = {'root', 'queue', 'code_roots', 'checks'}
            optional = {'environment', 'evidence_exclude'}
            if not required <= set(selected) or set(selected) - required - optional:
                raise ValueError('invalid pinned-base project registration')
            scope_contains(selected['root'], selected['root'])
            scope_contains(selected['queue'], selected['queue'])
            if Path(selected['queue']).parent != Path(selected['root']) / 'openspec':
                raise ValueError('invalid pinned-base project queue')
        areas = selected['code_roots']
        if (not isinstance(areas, list) or not areas
                or any(not isinstance(area, str) for area in areas)
                or len(set(areas)) != len(areas)):
            raise ValueError('invalid pinned-base code roots')
        for area in areas:
            scope_contains(area, area)
        projects._argv_commands(selected['checks'], 'pinned-base checks')
        environment = selected.get('environment', {})
        if not isinstance(environment, dict) or set(environment) - {'lockfiles', 'prepare'}:
            raise ValueError('invalid pinned-base environment')
        locks = environment.get('lockfiles', [])
        if (not isinstance(locks, list) or any(not isinstance(lock, str) or lock == '.' for lock in locks)
                or len(set(locks)) != len(locks)):
            raise ValueError('invalid pinned-base environment lockfiles')
        for lock in locks:
            scope_contains(lock, lock)
        projects._argv_commands(environment.get('prepare', []), 'pinned-base preparation', empty=True)
        paths = selected.get('evidence_exclude', [])
        if (not isinstance(paths, list) or any(not isinstance(path, str) for path in paths)
                or len(set(paths)) != len(paths)):
            raise ValueError('invalid pinned-base evidence exclusions')
        for path in paths:
            scope_contains(path, path)  # Validate lexically without consulting the changed tree.
            exclusions.add(path)
    return sorted(exclusions)


def _public(root, rel, *, exists=False, strict_ignored=True, exclusions=()):
    path = relative_path(root, rel, exists=exists)
    if _private(rel, exclusions):
        raise ValueError(f'private/runtime source is not review material: {rel}')
    ignore_args = ['--no-index'] if strict_ignored else []
    if subprocess.run(['git', '-C', str(root), 'check-ignore', *ignore_args, '-q', '--', rel]).returncode == 0:
        raise ValueError(f'ignored source must not enter review bundle: {rel}')
    return path


def _inventory(root, scope, *, empty=False, strict_ignored=True, exclusions=()):
    _scope(scope, empty=empty)
    hashes, contents, modes = {}, {}, {}
    for rel in scope:
        path = _public(root, rel, exists=True, strict_ignored=strict_ignored, exclusions=exclusions)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f'non-regular review source: {rel}')
            data = stream.read()
            after = os.fstat(stream.fileno())
            current = path.stat(follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode)
        if identity(before) != identity(after) or identity(current) != identity(before):
            raise ValueError(f'source changed during capture: {rel}')
        contents[rel] = data
        hashes[rel] = _hash(data)
        modes[rel] = _mode(before.st_mode)
    return hashes, contents, modes


def inventory(root: Path, scope: list[str]) -> tuple[dict, dict]:
    """Compatibility view; mode-aware materialization uses the full inventory."""
    hashes, contents, _ = _inventory(root, scope)
    return hashes, contents


def revision(files, modes, deleted):
    """Canonical schema-3 identity; modes and deleted originals are relevant bytes."""
    payload = {'input_files': files, 'input_modes': modes, 'deleted_files': deleted}
    return _hash(json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def _tree(repository, base, rel):
    if not isinstance(base, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', base):
        raise ValueError('deleted source requires an immutable base commit')
    output = subprocess.check_output(['git', '--git-dir', str(repository), 'ls-tree', '-z', base, '--', rel])
    if subprocess.check_output(['git', '--git-dir', str(repository), 'cat-file', '-t', base], text=True).strip() != 'commit':
        raise ValueError('deleted source base is not a commit object')
    records = [r for r in output.split(b'\0') if r]
    if len(records) != 1:
        raise ValueError(f'deleted source absent from pinned base: {rel}')
    header, filename = records[0].split(b'\t', 1)
    mode, kind, oid = header.decode().split()
    if filename.decode() != rel or kind != 'blob' or mode not in MODES:
        raise ValueError(f'deleted symlink/non-regular source is forbidden: {rel}')
    content = subprocess.check_output(['git', '--git-dir', str(repository), 'cat-file', 'blob', oid])
    return {'sha256': _hash(content), 'mode': mode}, content


def _deleted(root, repository, base, scope, *, exclusions=()):
    _scope(scope, empty=True)
    records, contents = {}, {}
    for rel in scope:
        path = _public(root, rel, exclusions=exclusions)
        if os.path.lexists(path):
            raise ValueError(f'deleted source was recreated or still exists: {rel}')
        records[rel], contents[rel] = _tree(repository, base, rel)
    return records, contents


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
        if not os.path.lexists(path):
            deleted.append(rel)
        elif path.is_symlink():
            if mode != '120000': changed.add(rel)
        elif mode in MODES and (not path.is_file() or _mode(path.stat().st_mode) != mode):
            changed.add(rel)
        elif mode not in MODES and mode != '160000':
            changed.add(rel)
    return {'input_scope': sorted(p for p in changed if os.path.lexists(root / p)), 'deleted_scope': sorted(deleted)}


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
    exclusions = _exclusions(worktree, project)
    deleted_exclusions = sorted(set(exclusions) | set(_base_exclusions(common, base))) if deleted_scope else exclusions
    files, contents, modes = _inventory(worktree, scope, empty=True, exclusions=exclusions)
    deleted, deleted_contents = _deleted(worktree, common, base, deleted_scope, exclusions=deleted_exclusions)
    manifest = dict(schema_version=3, kind='retained-review-source', project=project, change=change, run_id=run_id,
                    policy=policy, repository=common, input_head=head, base_commit=base, input_scope=scope,
                    input_files=files, input_modes=modes, deleted_files=deleted, input_revision=revision(files, modes, deleted),
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
        again, _, again_modes = _inventory(worktree, scope, empty=True, exclusions=exclusions)
        again_deleted, _ = _deleted(worktree, common, base, deleted_scope, exclusions=deleted_exclusions)
        if _exclusions(worktree, project) != exclusions:
            raise ValueError('evidence policy changed during materialization; no bundle published')
        if (again, again_modes, again_deleted) != (files, modes, deleted) or _git(worktree, 'rev-parse', 'HEAD') != head:
            raise ValueError('source changed during materialization; no bundle published')
        destination.mkdir()
        for item in tmp.iterdir():
            item.rename(destination / item.name)
    for path in sorted(destination.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir(): path.chmod(0o555)
        elif path.name == 'manifest.json' and path.parent == destination: path.chmod(0o444)
    destination.chmod(0o555)
    return manifest


def _retained(bundle, folder, files, modes=None, *, public=False, exclusions=()):
    base = bundle / folder
    if base.is_symlink() or (files and not base.is_dir()):
        raise ValueError(f'retained {folder} inventory mismatch')
    actual = sorted(p.relative_to(base).as_posix() for p in base.rglob('*') if p.is_file() or p.is_symlink())
    if actual != sorted(files):
        raise ValueError(f'retained {folder} inventory mismatch')
    for rel, expected in files.items():
        if public and _private(rel, exclusions):
            raise ValueError(f'private/runtime source is not review material: {rel}')
        path = relative_path(base, rel, exists=True)
        if not path.is_file() or _hash(path.read_bytes()) != expected:
            raise ValueError(f'retained source changed: {rel}')
        if modes is not None and _mode(path.stat().st_mode) != modes[rel]:
            raise ValueError(f'retained source mode changed: {rel}')


def verify(bundle: Path, worktree: Path | None = None, *, current_head_required: bool = True) -> dict:
    bundle = Path(bundle)
    manifest = json.loads((bundle / 'manifest.json').read_text())
    version = manifest.get('schema_version')
    if version not in (2, 3) or manifest.get('kind') != 'retained-review-source':
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
        if not isinstance(modes, dict) or modes.keys() != files.keys() or any(not isinstance(m, str) or m not in MODES for m in modes.values()) or not isinstance(deleted, dict) or set(files) & set(deleted) or not (files or deleted):
            raise ValueError('invalid retained source modes/deletions')
        for rel, entry in deleted.items():
            if not isinstance(entry, dict) or set(entry) != {'sha256', 'mode'} or not isinstance(entry['mode'], str) or entry['mode'] not in MODES:
                raise ValueError('invalid deleted source identity')
        declared_deleted_exclusions = manifest.get('deleted_evidence_exclude', exclusions)
        if not isinstance(declared_deleted_exclusions, list):
            raise ValueError('invalid deleted evidence exclusions')
        for excluded in declared_deleted_exclusions:
            scope_contains(excluded, excluded)
        deleted_exclusions = sorted(set(exclusions) | set(declared_deleted_exclusions)
                                    | (set(_base_exclusions(manifest['repository'], manifest['base_commit'])) if deleted else set()))
        if revision(files, modes, deleted) != manifest['input_revision']:
            raise ValueError('retained revision mismatch')
        _retained(bundle, 'source', files, modes, public=True, exclusions=exclusions)
        _retained(bundle, 'deleted-source', {p: d['sha256'] for p, d in deleted.items()}, {p: d['mode'] for p, d in deleted.items()}, public=True, exclusions=deleted_exclusions)
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
        if current_head_required and _git(worktree, 'rev-parse', 'HEAD') != manifest['input_head']:
            raise ValueError('current final bytes differ from reviewed source')
        live_exclusions = _exclusions(worktree, manifest['project']) if version == 3 else []
        current, _, current_modes = _inventory(worktree, manifest['input_scope'], empty=version == 3,
                                               strict_ignored=version == 3, exclusions=live_exclusions)
        if current != files or (version == 3 and current_modes != manifest['input_modes']):
            raise ValueError('current final bytes/modes differ from reviewed source')
        if version == 3:
            _deleted(worktree, manifest['repository'], manifest['base_commit'], sorted(manifest['deleted_files']),
                     exclusions=sorted(set(live_exclusions) | set(deleted_exclusions)))
    return manifest
