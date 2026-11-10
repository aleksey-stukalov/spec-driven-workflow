"""Retained source schema 3: executable modes, exact deletions and coverage."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import evidence
import plan_runtime


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.PIPE).strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / 'repo'; root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.name', 'Synthetic Test'); git(root, 'config', 'user.email', 'test@example.invalid')
    (root / 'script.sh').write_bytes(b'#!/bin/sh\nexit 0\n'); (root / 'script.sh').chmod(0o755)
    (root / 'normal.py').write_text('value = 1\n')
    (root / 'deleted.sh').write_bytes(b'#!/bin/sh\n# original deleted executable\n'); (root / 'deleted.sh').chmod(0o755)
    (root / 'ignored.secret').write_text('synthetic ignored original')
    (root / '.env').write_text('SYNTHETIC=true')
    (root / 'old-link').symlink_to('script.sh')
    git(root, 'add', '.'); git(root, 'commit', '-m', 'synthetic public and private originals')
    (root / '.gitignore').write_text('ignored.secret\n')
    git(root, 'add', '.gitignore'); git(root, 'commit', '-m', 'ignore synthetic private material')
    return root


def capture(root, target, scope=None, deleted_scope=None):
    return evidence.materialize(root, target, ['normal.py', 'script.sh'] if scope is None else scope,
                                deleted_scope=deleted_scope, project='synthetic', change='26-11-09-901-source', run_id='run',
                                base=git(root, 'rev-parse', 'HEAD'), policy='plans-v1')


def test_modes_are_preserved_bound_and_live_mode_only_changes_reject(repository, tmp_path):
    target = tmp_path / 'bundle'; manifest = capture(repository, target)
    assert manifest['schema_version'] == 3
    assert manifest['input_modes'] == {'normal.py': '100644', 'script.sh': '100755'}
    assert manifest['input_revision'] == evidence.revision(manifest['input_files'], manifest['input_modes'], {})
    assert (target / 'source/script.sh').stat().st_mode & 0o777 == 0o555
    assert (target / 'source/normal.py').stat().st_mode & 0o777 == 0o444
    assert subprocess.run([str(target / 'source/script.sh')]).returncode == 0
    before = manifest['input_revision']
    (repository / 'script.sh').chmod(0o644)
    with pytest.raises(ValueError, match='bytes/modes'): evidence.verify(target, repository)
    after = capture(repository, tmp_path / 'mode-changed')['input_revision']
    assert before != after


def test_retained_mode_only_mutation_rejects_even_when_bytes_unchanged(repository, tmp_path):
    target = tmp_path / 'bundle'; capture(repository, target)
    (target / 'source/script.sh').chmod(0o444)
    with pytest.raises(ValueError, match='mode changed'): evidence.verify(target)


def test_deletion_only_bundle_retains_original_base_bytes_and_executable_mode(repository, tmp_path):
    original = (repository / 'deleted.sh').read_bytes(); (repository / 'deleted.sh').unlink()
    target = tmp_path / 'deletion'; manifest = capture(repository, target, [], ['deleted.sh'])
    assert manifest['input_files'] == {} and manifest['input_modes'] == {}
    assert manifest['deleted_files'] == {'deleted.sh': {'sha256': hashlib.sha256(original).hexdigest(), 'mode': '100755'}}
    assert (target / 'deleted-source/deleted.sh').read_bytes() == original
    assert (target / 'deleted-source/deleted.sh').stat().st_mode & 0o777 == 0o555
    assert evidence.verify(target, repository) == manifest
    (repository / 'deleted.sh').write_bytes(original)
    with pytest.raises(ValueError, match='recreated'): evidence.verify(target, repository)


@pytest.mark.parametrize('mutation', ['missing', 'bytes', 'mode', 'extra'])
def test_deleted_retained_original_missing_tampered_or_extra_rejects(repository, tmp_path, mutation):
    (repository / 'deleted.sh').unlink()
    target = tmp_path / 'deletion'; capture(repository, target, [], ['deleted.sh'])
    directory = target / 'deleted-source'; directory.chmod(0o755)
    path = directory / 'deleted.sh'
    if mutation == 'missing': path.unlink()
    if mutation == 'bytes': path.chmod(0o755); path.write_text('different original')
    if mutation == 'mode': path.chmod(0o444)
    if mutation == 'extra': (directory / 'unclaimed.py').write_text('extra source')
    with pytest.raises(ValueError, match='inventory mismatch|source changed|mode changed'): evidence.verify(target)


def test_deleted_manifest_cannot_rebind_original_to_other_git_base(repository, tmp_path):
    (repository / 'deleted.sh').unlink()
    target = tmp_path / 'deletion'; manifest = capture(repository, target, [], ['deleted.sh'])
    # A self-consistent tampered retained blob still must match the pinned base.
    retained = target / 'deleted-source/deleted.sh'; retained.chmod(0o755); retained.write_text('forged original')
    manifest['deleted_files']['deleted.sh']['sha256'] = hashlib.sha256(retained.read_bytes()).hexdigest()
    manifest['input_revision'] = evidence.revision(manifest['input_files'], manifest['input_modes'], manifest['deleted_files'])
    path = target / 'manifest.json'; path.chmod(0o644); path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='pinned base'): evidence.verify(target)


@pytest.mark.parametrize('relative', ['.env', 'ignored.secret', 'old-link'])
def test_private_ignored_and_deleted_symlink_originals_reject(repository, tmp_path, relative):
    (repository / relative).unlink()
    with pytest.raises(ValueError, match='private/runtime|ignored source|symlink/non-regular'):
        capture(repository, tmp_path / 'forbidden', [], [relative])
    assert not (tmp_path / 'forbidden').exists()


def test_deleted_scope_must_be_sorted_disjoint_and_actually_absent(repository, tmp_path):
    with pytest.raises(ValueError, match='still exists'): capture(repository, tmp_path / 'exists', [], ['deleted.sh'])
    with pytest.raises(ValueError, match='disjoint'): capture(repository, tmp_path / 'overlap', ['normal.py'], ['normal.py'])
    with pytest.raises(ValueError, match='sorted'): capture(repository, tmp_path / 'unsorted', [], ['normal.py', 'deleted.sh'])
    with pytest.raises(ValueError, match='pinned base'): capture(repository, tmp_path / 'never-existed', [], ['missing.py'])


def test_changed_scope_covers_new_staged_modified_deleted_and_mode_only(repository):
    base = git(repository, 'rev-parse', 'HEAD')
    assert evidence.changed_scope(repository, base) == {'input_scope': [], 'deleted_scope': []}
    git(repository, 'config', 'core.filemode', 'false')
    (repository / 'script.sh').chmod(0o644)
    (repository / 'normal.py').write_text('value = 2\n')
    (repository / 'deleted.sh').unlink()
    (repository / 'untracked.py').write_text('new untracked\n')
    (repository / 'staged.py').write_text('new staged\n'); git(repository, 'add', 'staged.py')
    result = evidence.changed_scope(repository, base)
    assert result == {'input_scope': ['normal.py', 'script.sh', 'staged.py', 'untracked.py'], 'deleted_scope': ['deleted.sh']}


def test_renamed_source_keeps_old_deletion_and_new_source_coverage(repository):
    base = git(repository, 'rev-parse', 'HEAD')
    (repository / 'normal.py').rename(repository / 'renamed.py')
    assert evidence.changed_scope(repository, base) == {'input_scope': ['renamed.py'], 'deleted_scope': ['normal.py']}


@pytest.mark.parametrize('relative', ['script.sh', 'ignored.secret'])
def test_historical_schema_two_keeps_its_original_identity_and_semantics(repository, tmp_path, relative):
    target = tmp_path / 'historical'; (target / 'source').mkdir(parents=True)
    content = (repository / relative).read_bytes(); (target / 'source' / relative).write_bytes(content)
    files = {relative: hashlib.sha256(content).hexdigest()}
    manifest = dict(schema_version=2, kind='retained-review-source', input_files=files, input_scope=[relative],
                    input_revision=hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                    repository=str(Path(git(repository, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()), input_head=git(repository, 'rev-parse', 'HEAD'))
    path = target / 'manifest.json'; path.write_text(json.dumps(manifest)); original = path.read_bytes()
    assert evidence.verify(target, repository) == manifest
    assert path.read_bytes() == original and manifest['schema_version'] == 2


def test_mode_mutation_during_capture_never_publishes_bundle(repository, tmp_path, monkeypatch):
    original = evidence._inventory
    calls = 0
    def mutate(root, scope, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2: (root / 'script.sh').chmod(0o644)
        return original(root, scope, **kwargs)
    monkeypatch.setattr(evidence, '_inventory', mutate)
    target = tmp_path / 'race'
    with pytest.raises(ValueError, match='changed during materialization'): capture(repository, target)
    assert not target.exists()


def test_deleted_recreation_during_capture_never_publishes_bundle(repository, tmp_path, monkeypatch):
    (repository / 'deleted.sh').unlink()
    original = evidence._deleted
    calls = 0
    def mutate(root, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2: (root / 'deleted.sh').write_text('recreated during capture')
        return original(root, *args, **kwargs)
    monkeypatch.setattr(evidence, '_deleted', mutate)
    target = tmp_path / 'race'
    with pytest.raises(ValueError, match='recreated'): capture(repository, target, [], ['deleted.sh'])
    assert not target.exists()
