"""Typed discovery evidence preserves lexical identity without retaining aliases."""
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from test_source_integrity import repository, git
import evidence
import projects
import skill_links

LEAF = '.agents/skills/sdw-run'
CANONICAL = skill_links.canonical_skill(LEAF)
TARGET = skill_links.expected_target(LEAF)


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def link(root):
    write(root, CANONICAL, 'canonical skill\n')
    (root / LEAF).parent.mkdir(parents=True, exist_ok=True)
    (root / LEAF).symlink_to(TARGET, target_is_directory=True)


def capture(root, destination, scope, deleted=(), base=None):
    return evidence.materialize(root, destination, sorted(scope), deleted_scope=sorted(deleted),
        project='synthetic', change='26-11-10-005-harness-owned-workflow', run_id='typed',
        base=base or git(root, 'rev-parse', 'HEAD'), policy='plans-v1')


def test_link_storage_is_inert_and_schema_four_has_separate_identity(repository, tmp_path):
    link(repository)
    bundle = tmp_path / 'bundle'
    manifest = capture(repository, bundle, [LEAF, CANONICAL])
    assert manifest['schema_version'] == 4
    assert manifest['input_modes'][LEAF] == '120000'
    assert manifest['input_files'][LEAF] == hashlib.sha256(TARGET.encode()).hexdigest()
    assert not (bundle / 'source' / LEAF).is_symlink()
    assert (bundle / 'source' / LEAF).read_text() == TARGET
    assert evidence.verify(bundle, repository) == manifest
    assert evidence.revision(manifest['input_files'], manifest['input_modes'], {}, 3) != manifest['input_revision']
    assert LEAF in evidence.changed_scope(repository, manifest['base_commit'])['input_scope']
    (repository / LEAF).unlink()
    (repository / LEAF).symlink_to('../../agentic_harness/skills/sdw-review')
    with pytest.raises(ValueError, match='invalid discovery link'):
        evidence.verify(bundle, repository)


def test_link_requires_explicit_canonical_scope(repository, tmp_path):
    link(repository)
    with pytest.raises(ValueError, match='explicit canonical'):
        capture(repository, tmp_path / 'bad', [LEAF])
    assert not (tmp_path / 'bad').exists()
    with pytest.raises(ValueError, match='aliased'):
        capture(repository, tmp_path / 'child', [LEAF + '/SKILL.md'])


def test_displaced_copy_is_deleted_even_when_canonical_is_visible_through_link(repository, tmp_path):
    old = LEAF + '/SKILL.md'
    path = write(repository, old, 'old copied body\n')
    path.chmod(0o755)
    git(repository, 'add', '.'); git(repository, 'commit', '-m', 'old copied discovery')
    base = git(repository, 'rev-parse', 'HEAD')
    git(repository, 'config', 'core.filemode', 'false')
    path.unlink(); path.parent.rmdir(); link(repository)
    changed = evidence.changed_scope(repository, base)
    assert old in changed['deleted_scope'] and old not in changed['input_scope']
    assert LEAF in changed['input_scope'] and CANONICAL in changed['input_scope']
    manifest = capture(repository, tmp_path / 'conversion', [LEAF, CANONICAL], [old], base)
    assert manifest['deleted_files'][old]['mode'] == '100755'
    assert (tmp_path / 'conversion/deleted-source' / old).read_text() == 'old copied body\n'
    assert evidence.verify(tmp_path / 'conversion', repository) == manifest


def test_deleted_approved_link_original_is_inert(repository, tmp_path):
    link(repository)
    git(repository, 'add', '.'); git(repository, 'commit', '-m', 'approved link')
    (repository / LEAF).unlink()
    manifest = capture(repository, tmp_path / 'deleted', [], [LEAF])
    retained = tmp_path / 'deleted/deleted-source' / LEAF
    assert not retained.is_symlink() and retained.read_text() == TARGET
    assert manifest['deleted_files'][LEAF]['mode'] == '120000'
    assert evidence.verify(tmp_path / 'deleted', repository) == manifest


@pytest.mark.parametrize('direction', ['file-to-link', 'link-to-file'])
def test_same_leaf_type_replacement_is_explicitly_unsupported(repository, tmp_path, direction):
    if direction == 'file-to-link':
        write(repository, LEAF, 'regular')
    else:
        link(repository)
    git(repository, 'add', '.'); git(repository, 'commit', '-m', 'original type')
    base = git(repository, 'rev-parse', 'HEAD')
    (repository / LEAF).unlink()
    if direction == 'file-to-link':
        link(repository)
    else:
        (repository / LEAF).write_text('regular replacement')
    with pytest.raises(ValueError, match='unsupported same-leaf'):
        evidence.changed_scope(repository, base)
    with pytest.raises(ValueError, match='unsupported same-leaf'):
        capture(repository, tmp_path / 'bad', [LEAF, CANONICAL], base=base)


def test_unsafe_untracked_and_deleted_links_never_disappear(repository):
    bad = repository / 'unsafe-link'
    bad.symlink_to('normal.py')
    with pytest.raises(ValueError, match='aliased'):
        evidence.changed_scope(repository, git(repository, 'rev-parse', 'HEAD'))
    git(repository, 'add', 'unsafe-link'); git(repository, 'commit', '-m', 'unsafe original')
    bad.unlink()
    with pytest.raises(ValueError, match='symlink/non-regular'):
        evidence.changed_scope(repository, git(repository, 'rev-parse', 'HEAD'))


@pytest.mark.parametrize('mutation', ['extra-empty-directory', 'real-symlink', 'target-text'])
def test_retained_typed_tree_rejects_tampering(repository, tmp_path, mutation):
    link(repository)
    bundle = tmp_path / 'bundle'
    capture(repository, bundle, [LEAF, CANONICAL])
    parent = bundle / 'source' / Path(LEAF).parent
    parent.chmod(0o755)
    if mutation == 'extra-empty-directory':
        (parent / 'extra').mkdir()
    else:
        leaf = bundle / 'source' / LEAF
        leaf.chmod(0o644)
        if mutation == 'real-symlink':
            leaf.unlink(); leaf.symlink_to(TARGET)
        else:
            leaf.write_text('different target')
    with pytest.raises(ValueError):
        evidence.verify(bundle)


def test_link_mutation_during_capture_publishes_nothing(repository, tmp_path, monkeypatch):
    link(repository)
    original = evidence._inventory
    calls = 0
    def mutate(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            (repository / LEAF).unlink()
            (repository / LEAF).symlink_to('../../agentic_harness/skills/sdw-review')
        return original(*args, **kwargs)
    monkeypatch.setattr(evidence, '_inventory', mutate)
    with pytest.raises(ValueError):
        capture(repository, tmp_path / 'bad', [LEAF, CANONICAL])
    assert not (tmp_path / 'bad').exists()


def test_historical_schema_three_retains_original_revision_formula(repository, tmp_path):
    bundle = tmp_path / 'historical'
    manifest = capture(repository, bundle, ['normal.py'])
    manifest['schema_version'] = 3
    manifest['input_revision'] = evidence.revision(manifest['input_files'], manifest['input_modes'], {})
    path = bundle / 'manifest.json'; path.chmod(0o644); path.write_text(json.dumps(manifest))
    original = path.read_bytes()
    assert evidence.verify(bundle, repository) == manifest
    assert path.read_bytes() == original


@pytest.mark.parametrize('package', ['agentic_harness', '_agentic_harness'])
@pytest.mark.parametrize('version', [1, 2, 3])
def test_historical_privacy_uses_exact_schema_and_package(repository, package, version):
    settings = {'code_roots': ['.'], 'checks': [['true']], 'evidence_exclude': ['private']}
    binding = {'root': '.'}
    if version == 1:
        binding.update(queue='openspec/queue.yaml', **settings)
    else:
        path = 'openspec/workflow.yaml' if version == 2 else package + '/config/workflow.yaml'
        write(repository, path, yaml.safe_dump({'schema_version': 1, **settings}))
    write(repository, package + '/projects.yaml', yaml.safe_dump({'schema_version': version, 'projects': {'synthetic': binding}}))
    git(repository, 'add', '.'); git(repository, 'commit', '-m', 'privacy authority')
    base = git(repository, 'rev-parse', 'HEAD')
    assert evidence._base_exclusions(repository / '.git', base) == ['private']
    alternate = package + '/config/workflow.yaml' if version < 3 else 'openspec/workflow.yaml'
    write(repository, alternate, yaml.safe_dump({'schema_version': 1, **settings}))
    git(repository, 'add', '.'); git(repository, 'commit', '-m', 'ambiguous privacy authority')
    with pytest.raises(ValueError, match='ambiguous pinned-base'):
        evidence._base_exclusions(repository / '.git', git(repository, 'rev-parse', 'HEAD'))


def test_same_bytes_parent_replacement_during_capture_is_rejected(repository, tmp_path, monkeypatch):
    link(repository)
    original = evidence._inventory
    calls = 0
    def mutate(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            parent = (repository / CANONICAL).parent
            moved = parent.with_name('moved')
            parent.rename(moved)
            parent.mkdir()
            (parent / 'SKILL.md').write_bytes((moved / 'SKILL.md').read_bytes())
        return original(*args, **kwargs)
    monkeypatch.setattr(evidence, '_inventory', mutate)
    with pytest.raises(ValueError, match='changed during materialization'):
        capture(repository, tmp_path / 'bad', [LEAF, CANONICAL])
    assert not (tmp_path / 'bad').exists()


def test_displaced_original_still_honors_git_ignore_patterns(repository, tmp_path):
    old = LEAF + '/SKILL.md'
    path = write(repository, old, 'old copied body')
    git(repository, 'add', '.'); git(repository, 'commit', '-m', 'copied original')
    base = git(repository, 'rev-parse', 'HEAD')
    path.unlink(); path.parent.rmdir(); link(repository)
    with (repository / '.gitignore').open('a') as stream:
        stream.write('\n.agents/skills/sdw-run/SKILL.md\n')
    with pytest.raises(ValueError, match='ignored source'):
        capture(repository, tmp_path / 'bad', [LEAF, CANONICAL], [old], base)
    assert not (tmp_path / 'bad').exists()


@pytest.mark.parametrize('package', ['agentic_harness', '_agentic_harness'])
@pytest.mark.parametrize('corruption', ['missing', 'yaml', 'unknown-field', 'symlink'])
def test_invalid_historical_schema_three_settings_never_use_live_substitute(repository, package, corruption):
    settings = {'schema_version': 1, 'code_roots': ['.'], 'checks': [['true']], 'evidence_exclude': ['private']}
    relative = package + '/config/workflow.yaml'
    index = {'schema_version': 3, 'projects': {'synthetic': {'root': '.'}}}
    write(repository, package + '/projects.yaml', yaml.safe_dump(index))
    if corruption == 'yaml':
        write(repository, relative, 'schema_version: [\n')
    elif corruption == 'unknown-field':
        write(repository, relative, yaml.safe_dump({**settings, 'unknown': True}))
    elif corruption == 'symlink':
        target = write(repository, relative, '')
        target.unlink(); target.symlink_to('../../normal.py')
    git(repository, 'add', '.'); git(repository, 'commit', '-m', 'invalid historical settings')
    base = git(repository, 'rev-parse', 'HEAD')
    path = repository / relative
    if path.is_symlink():
        path.unlink()
    write(repository, relative, yaml.safe_dump({**settings, 'evidence_exclude': []}))
    with pytest.raises(ValueError, match='pinned-base'):
        evidence._base_exclusions(repository / '.git', base)


@pytest.mark.parametrize('mutation', ['link', 'file', 'parent'])
def test_live_verification_rejects_earlier_input_replacement_during_later_read(repository, tmp_path, monkeypatch, mutation):
    link(repository)
    early = LEAF if mutation == 'link' else 'earlier/input.py'
    if mutation != 'link':
        write(repository, early, 'reviewed earlier input\n')
    bundle = tmp_path / 'bundle'
    capture(repository, bundle, [LEAF, CANONICAL, early] if early != LEAF else [LEAF, CANONICAL])
    original_open = evidence.os.open
    mutated = False
    # Select a later input lexically. Ordinary-file cases use a final z-file.
    later = CANONICAL
    if mutation != 'link':
        later = 'z-last.py'
        write(repository, later, 'later input\n')
        bundle = tmp_path / 'ordinary-bundle'
        capture(repository, bundle, [early, later])
    def mutate_when_later_opened(path, flags, *args, **kwargs):
        nonlocal mutated
        if Path(path) == repository / later and not mutated:
            mutated = True
            leaf = repository / early
            if mutation == 'link':
                leaf.unlink(); leaf.symlink_to('../../outside')
            elif mutation == 'file':
                data = leaf.read_bytes()
                leaf.unlink(); leaf.write_bytes(data)
            else:
                leaf.parent.rename(leaf.parent.with_name('detached-earlier'))
                leaf.parent.mkdir(); leaf.write_text('reviewed earlier input\n')
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(evidence.os, 'open', mutate_when_later_opened)
    with pytest.raises(ValueError):
        evidence.verify(bundle, repository)
    assert mutated
    # The retained source remains independently valid after live failure.
    evidence.verify(bundle)


@pytest.mark.parametrize('policy', ['settings', 'index', 'map', 'native'])
def test_live_verification_rejects_policy_replacement_during_inventory(repository, tmp_path, monkeypatch, policy):
    settings = {'schema_version': 1, 'code_roots': ['.'], 'checks': [['true']], 'evidence_exclude': []}
    write(repository, projects.INDEX_PATH, yaml.safe_dump({'schema_version': 3, 'projects': {'synthetic': {'root': '.'}}}))
    settings_path = projects.workflow_path('.')
    write(repository, settings_path, yaml.safe_dump(settings))
    write(repository, 'openspec/config.yaml', 'schema: spec-driven\n')
    write(repository, 'openspec/dependency-map.yaml', 'queue: []\n')
    bundle = tmp_path / 'bundle'
    capture(repository, bundle, ['normal.py'])
    relative = {'settings': settings_path, 'index': projects.INDEX_PATH,
                'map': 'openspec/dependency-map.yaml', 'native': 'openspec/config.yaml'}[policy]
    original_open = evidence.os.open
    mutated = False
    def mutate_when_input_opened(path, flags, *args, **kwargs):
        nonlocal mutated
        if Path(path) == repository / 'normal.py' and not mutated:
            mutated = True
            leaf = repository / relative
            data = leaf.read_bytes()
            leaf.unlink(); leaf.write_bytes(data)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(evidence.os, 'open', mutate_when_input_opened)
    with pytest.raises(ValueError, match='policy changed during verification'):
        evidence.verify(bundle, repository)
    assert mutated


def test_live_verification_checks_head_interval_even_when_historical_head_allowed(repository, tmp_path, monkeypatch):
    bundle = tmp_path / 'bundle'
    capture(repository, bundle, ['normal.py'])
    git(repository, 'commit', '--allow-empty', '-m', 'new stable head')
    evidence.verify(bundle, repository, current_head_required=False)
    original = evidence._inventory
    def move_head(*args, **kwargs):
        result = original(*args, **kwargs)
        git(repository, 'commit', '--allow-empty', '-m', 'racing head')
        return result
    monkeypatch.setattr(evidence, '_inventory', move_head)
    with pytest.raises(ValueError, match='source changed during verification'):
        evidence.verify(bundle, repository, current_head_required=False)


def test_live_verification_rejects_recreated_deleted_input_at_end_of_interval(repository, tmp_path, monkeypatch):
    path = write(repository, 'removed.py', 'old input\n')
    git(repository, 'add', '.'); git(repository, 'commit', '-m', 'old input')
    path.unlink()
    bundle = tmp_path / 'bundle'
    capture(repository, bundle, ['normal.py'], ['removed.py'])
    original = evidence._deleted
    def recreate_after_deleted_check(*args, **kwargs):
        result = original(*args, **kwargs)
        path.write_text('concurrent recreated input\n')
        return result
    monkeypatch.setattr(evidence, '_deleted', recreate_after_deleted_check)
    with pytest.raises(ValueError, match='source changed during verification'):
        evidence.verify(bundle, repository)
    assert path.read_text() == 'concurrent recreated input\n'
