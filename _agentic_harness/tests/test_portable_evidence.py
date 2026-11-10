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
    path = repository / '_agentic_harness/projects.yaml'
    config = yaml.safe_load(path.read_text())
    if config['schema_version'] == 2:
        path = repository / config['projects']['synthetic']['root'] / 'openspec/workflow.yaml'
        config = yaml.safe_load(path.read_text())
        config['evidence_exclude'] = exclusions
    else:
        config['projects']['synthetic']['evidence_exclude'] = exclusions
    path.write_text(yaml.safe_dump(config))


def use_companion(repository):
    index = repository / '_agentic_harness/projects.yaml'
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


def test_dependency_reads_respect_other_domains_private_paths(repository, tmp_path):
    other = repository / 'other/openspec'
    other.mkdir(parents=True)
    (other / 'config.yaml').write_text('schema: spec-driven\n')
    (other / 'queue.yaml').write_text('queue: []\n')
    private = repository / 'other/private.json'
    private.write_text('{}\n')
    config_path = repository / '_agentic_harness/projects.yaml'
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
    (repository / '_agentic_harness/projects.yaml').unlink()
    assert evidence._base_exclusions(repository / '.git', base) == ['private-data.json']


@pytest.mark.parametrize('corruption', [
    'missing', 'symlink', 'invalid-yaml', 'duplicate-field', 'unsupported-version',
    'missing-checks', 'unknown-field', 'invalid-exclusions', 'unsafe-exclusion',
    'unsafe-root', 'absolute-root', 'noncanonical-root', 'invalid-environment',
])
def test_invalid_pinned_companion_fails_closed_even_after_live_repair(repository, corruption):
    use_companion(repository)
    path = repository / 'project/openspec/workflow.yaml'
    index = repository / '_agentic_harness/projects.yaml'
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
