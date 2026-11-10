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
    config['projects']['synthetic']['evidence_exclude'] = exclusions
    path.write_text(yaml.safe_dump(config))


def test_exclusion_is_a_path_boundary_not_a_string_prefix(repository, tmp_path):
    configure(repository, ['private-data'])
    for folder in ('private-data', 'private-data-public'):
        (repository / folder).mkdir()
        (repository / folder / 'example.json').write_text('{}\n')
    with pytest.raises(ValueError, match='not review material'):
        capture(repository, tmp_path / 'blocked', ['private-data/example.json'])
    capture(repository, tmp_path / 'allowed', ['private-data-public/example.json'])


def test_new_live_exclusion_rejects_reuse_of_old_review(repository, tmp_path):
    target = tmp_path / 'bundle'
    capture(repository, target, ['source.py'])
    configure(repository, ['source.py'])
    with pytest.raises(ValueError, match='not review material'):
        evidence.verify(target, repository)
    assert evidence.verify(target)['input_scope'] == ['source.py']


def test_excluded_deleted_source_never_enters_bundle(repository, tmp_path):
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


def test_deleted_original_preserves_base_privacy_when_exclusion_is_retired(repository, tmp_path):
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


def test_policy_change_during_capture_never_publishes_bundle(repository, tmp_path, monkeypatch):
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
