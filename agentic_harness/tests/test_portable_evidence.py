"""Project-defined exclusions preserve ordinary source names and private boundaries."""
import json
from pathlib import Path
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import evidence
from test_runtime_integration import repository, capture, git


@pytest.mark.parametrize('relative', ['data/schema.json', 'runtime/engine.py', 'inputs/parser.py', 'out/formatter.py'])
def test_generic_source_directory_names_are_public(repository, tmp_path, relative):
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('synthetic source, not operational data\n')
    target = tmp_path / 'bundle'
    manifest = capture(repository, target, [relative])
    assert manifest['evidence_exclude'] == ['data/people.csv', 'runtime/state.json']
    assert evidence.verify(target, repository)['input_scope'] == [relative]


def configure(repository, exclusions):
    path = repository / 'agentic_harness/projects.yaml'
    config = yaml.safe_load(path.read_text())
    if config['schema_version'] == 2:
        path = repository / config['projects']['synthetic']['root'] / 'openspec/workflow.yaml'
        config = yaml.safe_load(path.read_text())
        config['evidence_exclude'] = exclusions
    else:
        config['projects']['synthetic']['evidence_exclude'] = exclusions
    path.write_text(yaml.safe_dump(config))


def use_companion(repository):
    index = repository / 'agentic_harness/projects.yaml'
    data = yaml.safe_load(index.read_text())
    entries = {}
    for name, selected in data['projects'].items():
        entries[name] = {'root': selected['root']}
        settings = {key: value for key, value in selected.items() if key not in {'root', 'queue'}}
        companion = repository / selected['root'] / 'openspec/workflow.yaml'
        companion.write_text(yaml.safe_dump({'schema_version': 1, **settings}))
    index.write_text(yaml.safe_dump({'schema_version': 2, 'projects': entries}))


@pytest.fixture(params=[1, 2])
def privacy_layout(repository, request):
    if request.param == 2:
        use_companion(repository)
    return request.param


def test_exclusion_is_a_path_boundary_not_a_string_prefix(repository, tmp_path):
    configure(repository, ['private-data'])
    for folder in ('private-data', 'private-data-public'):
        (repository / folder).mkdir()
        (repository / folder / 'example.json').write_text('{}\n')
    with pytest.raises(ValueError, match='not review material'):
        capture(repository, tmp_path / 'blocked', ['private-data/example.json'])
    capture(repository, tmp_path / 'allowed', ['private-data-public/example.json'])


def test_new_live_exclusion_rejects_reuse_of_old_review(repository, tmp_path, privacy_layout):
    target = tmp_path / 'bundle'
    capture(repository, target, ['source.py'])
    configure(repository, ['source.py'])
    with pytest.raises(ValueError, match='not review material'):
        evidence.verify(target, repository)
    assert evidence.verify(target)['input_scope'] == ['source.py']


def test_excluded_deleted_source_never_enters_bundle(repository, tmp_path, privacy_layout):
    path = repository / 'private-data.json'
    path.write_text('{}\n')
    configure(repository, ['private-data.json'])
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'declare synthetic exclusion')
    base = git(repository, 'rev-parse', 'HEAD')
    path.unlink()
    with pytest.raises(ValueError, match='not review material'):
        evidence.materialize(repository, tmp_path / 'bundle', [], deleted_scope=['private-data.json'],
                             project='synthetic', change='26-11-09-901-integration-contract',
                             run_id='run', base=base, policy='plans-v1')


def test_deleted_original_preserves_base_privacy_when_exclusion_is_retired(repository, tmp_path, privacy_layout):
    path = repository / 'private-data.json'
    path.write_text('{"synthetic-private": true}\n')
    configure(repository, ['private-data.json'])
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'declare synthetic exclusion')
    base = git(repository, 'rev-parse', 'HEAD')
    path.unlink()
    configure(repository, [])
    with pytest.raises(ValueError, match='not review material'):
        evidence.materialize(repository, tmp_path / 'bundle', [], deleted_scope=['private-data.json'],
                             project='synthetic', change='26-11-09-901-integration-contract',
                             run_id='run', base=base, policy='plans-v1')


def test_deleted_original_keeps_legacy_base_exclusions_after_directory_migration(repository, tmp_path, privacy_layout):
    private = repository / 'private-data.json'
    private.write_text('{"synthetic-private": true}\n')
    configure(repository, ['private-data.json'])
    current = repository / 'agentic_harness/projects.yaml'
    legacy = repository / '_agentic_harness/projects.yaml'
    legacy.parent.mkdir()
    current.rename(legacy)
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'Legacy package directory privacy authority')
    base = git(repository, 'rev-parse', 'HEAD')

    # The current layout and settings cannot erase the old commit's exclusions.
    legacy.rename(current)
    configure(repository, [])
    private.unlink()
    assert evidence._base_exclusions(repository / '.git', base) == ['private-data.json']
    target = tmp_path / 'forbidden-legacy-original'
    with pytest.raises(ValueError, match='not review material'):
        evidence.materialize(repository, target, [], deleted_scope=['private-data.json'],
                             project='synthetic', change='26-11-09-901-integration-contract',
                             run_id='run', base=base, policy='plans-v1')
    assert not target.exists()


@pytest.mark.parametrize('keep_current', [False, True], ids=['legacy-only', 'dual-index'])
def test_live_legacy_authority_cannot_silently_drop_privacy_rules(repository, tmp_path, privacy_layout, keep_current):
    current = repository / 'agentic_harness/projects.yaml'
    legacy = repository / '_agentic_harness/projects.yaml'
    legacy.parent.mkdir()
    legacy.write_bytes(current.read_bytes())
    if not keep_current:
        current.unlink()
    target = tmp_path / 'rejected-live-layout'
    with pytest.raises(ValueError, match='ambiguous workflow authority|legacy workflow directory'):
        capture(repository, target, ['source.py'])
    assert not target.exists()


def test_ambiguous_historical_indices_fail_even_after_live_layout_repair(repository, privacy_layout):
    current = repository / 'agentic_harness/projects.yaml'
    legacy = repository / '_agentic_harness/projects.yaml'
    legacy.parent.mkdir()
    legacy.write_bytes(current.read_bytes())
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'Ambiguous synthetic historical authority')
    base = git(repository, 'rev-parse', 'HEAD')
    legacy.unlink()
    with pytest.raises(ValueError, match='ambiguous pinned-base privacy policy'):
        evidence._base_exclusions(repository / '.git', base)


@pytest.mark.parametrize('corruption', ['invalid-yaml', 'duplicate-field', 'unsupported-version',
                                        'empty-projects', 'missing-fields', 'symlink'])
def test_malformed_legacy_base_index_cannot_fall_back_to_current_authority(repository, privacy_layout, corruption):
    current = repository / 'agentic_harness/projects.yaml'
    original = current.read_bytes()
    legacy = repository / '_agentic_harness/projects.yaml'
    legacy.parent.mkdir()
    current.rename(legacy)
    data = yaml.safe_load(original)
    if corruption == 'invalid-yaml':
        legacy.write_text('projects: [\n')
    elif corruption == 'duplicate-field':
        legacy.write_bytes(original + b'projects: {}\n')
    elif corruption == 'symlink':
        legacy.unlink()
        legacy.symlink_to('../project/openspec/config.yaml')
    else:
        if corruption == 'unsupported-version':
            data['schema_version'] = 7
        elif corruption == 'empty-projects':
            data['projects'] = {}
        elif corruption == 'missing-fields':
            data['projects']['synthetic'] = {}
        legacy.write_text(yaml.safe_dump(data))
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'Malformed synthetic legacy authority')
    base = git(repository, 'rev-parse', 'HEAD')
    legacy.unlink()
    current.write_bytes(original)
    with pytest.raises(ValueError):
        evidence._base_exclusions(repository / '.git', base)


def test_retained_old_paths_remain_original_and_rename_requires_new_evidence(repository, tmp_path):
    old_name = '_agentic_harness/policies/local.md'
    new_name = 'agentic_harness/policies/local.md'
    old = repository / old_name
    old.parent.mkdir(parents=True)
    old.write_text('The original policy bytes.\n')
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'Old public package path')
    base = git(repository, 'rev-parse', 'HEAD')
    target = tmp_path / 'original-bundle'
    manifest = capture(repository, target, [old_name])
    original = {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()}

    new = repository / new_name
    new.parent.mkdir(parents=True)
    old.rename(new)
    assert evidence.verify(target) == manifest
    with pytest.raises(ValueError, match='missing registered path'):
        evidence.verify(target, repository)
    assert {p.relative_to(target): p.read_bytes() for p in target.rglob('*') if p.is_file()} == original
    assert evidence.changed_scope(repository, base) == {
        'input_scope': [new_name], 'deleted_scope': [old_name],
    }
    replacement = evidence.materialize(repository, tmp_path / 'renamed-bundle', [new_name],
                                       deleted_scope=[old_name], project='synthetic',
                                       change=manifest['change'], run_id='run', base=base, policy='plans-v1')
    assert old_name in replacement['deleted_files']
    assert new_name in replacement['input_files']
    assert replacement['input_revision'] != manifest['input_revision']


def test_dependency_reads_respect_other_domains_private_paths(repository, tmp_path):
    other = repository / 'other/openspec'
    other.mkdir(parents=True)
    (other / 'config.yaml').write_text('schema: spec-driven\n')
    (other / 'queue.yaml').write_text('queue: []\n')
    private = repository / 'other/private.json'
    private.write_text('{}\n')
    config_path = repository / 'agentic_harness/projects.yaml'
    config = yaml.safe_load(config_path.read_text())
    config['projects']['other'] = {
        'root': 'other', 'queue': 'other/openspec/queue.yaml', 'code_roots': ['other'],
        'checks': [['true']], 'evidence_exclude': ['other/private.json'],
    }
    config_path.write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match='not review material'):
        capture(repository, tmp_path / 'bundle', ['other/private.json'])


def test_policy_change_during_capture_never_publishes_bundle(repository, tmp_path, monkeypatch, privacy_layout):
    original = evidence._inventory
    calls = 0
    def mutate(root, scope, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            configure(repository, ['source.py'])
        return original(root, scope, **kwargs)
    monkeypatch.setattr(evidence, '_inventory', mutate)
    target = tmp_path / 'bundle'
    with pytest.raises(ValueError, match='policy changed'):
        capture(repository, target, ['source.py'])
    assert not target.exists()


@pytest.mark.parametrize('exclusions', [None, '../outside', ['../outside'], [None], ['.', '.']])
def test_malformed_retained_exclusions_fail_closed(repository, tmp_path, exclusions):
    target = tmp_path / 'bundle'
    manifest = capture(repository, target, ['source.py'])
    manifest['evidence_exclude'] = exclusions
    path = target / 'manifest.json'
    path.chmod(0o644)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        evidence.verify(target)


def test_pinned_companion_is_read_from_base_when_live_files_are_removed(repository):
    use_companion(repository)
    configure(repository, ['private-data.json'])
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'Commit companion privacy policy')
    base = git(repository, 'rev-parse', 'HEAD')
    (repository / 'project/openspec/workflow.yaml').unlink()
    (repository / 'agentic_harness/projects.yaml').unlink()
    assert evidence._base_exclusions(repository / '.git', base) == ['private-data.json']


@pytest.mark.parametrize('corruption', [
    'missing', 'symlink', 'invalid-yaml', 'duplicate-field', 'unsupported-version',
    'missing-checks', 'unknown-field', 'invalid-exclusions', 'unsafe-exclusion',
    'unsafe-root', 'absolute-root', 'noncanonical-root', 'invalid-environment',
])
def test_invalid_pinned_companion_fails_closed_even_after_live_repair(repository, corruption):
    use_companion(repository)
    path = repository / 'project/openspec/workflow.yaml'
    index = repository / 'agentic_harness/projects.yaml'
    original, original_index = path.read_bytes(), index.read_bytes()
    config = yaml.safe_load(original)
    if corruption == 'missing':
        path.unlink()
    elif corruption == 'symlink':
        path.unlink()
        path.symlink_to('config.yaml')
    elif corruption == 'invalid-yaml':
        path.write_text('evidence_exclude: [\n')
    elif corruption == 'duplicate-field':
        path.write_bytes(original + b'evidence_exclude: []\n')
    elif corruption in {'unsafe-root', 'absolute-root', 'noncanonical-root'}:
        data = yaml.safe_load(original_index)
        data['projects']['synthetic']['root'] = {
            'unsafe-root': '../outside', 'absolute-root': '/project', 'noncanonical-root': './project',
        }[corruption]
        index.write_text(yaml.safe_dump(data))
    else:
        if corruption == 'unsupported-version':
            config['schema_version'] = 7
        elif corruption == 'missing-checks':
            config.pop('checks')
        elif corruption == 'unknown-field':
            config['evidence_excludes'] = ['private-data.json']
        elif corruption == 'invalid-exclusions':
            config['evidence_exclude'] = 'private-data.json'
        elif corruption == 'unsafe-exclusion':
            config['evidence_exclude'] = ['../private-data.json']
        elif corruption == 'invalid-environment':
            config['environment'] = {'lockfiles': ['.']}
        path.write_text(yaml.safe_dump(config))
    git(repository, 'add', '.')
    git(repository, 'commit', '-m', 'Invalid synthetic historical configuration')
    base = git(repository, 'rev-parse', 'HEAD')
    path.unlink(missing_ok=True)
    path.write_bytes(original)
    index.write_bytes(original_index)
    with pytest.raises(ValueError):
        evidence._base_exclusions(repository / '.git', base)
