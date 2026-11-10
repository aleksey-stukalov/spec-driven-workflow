"""CLI forwarding preserves project selection and upstream argument boundaries."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import harness


@pytest.mark.parametrize('arguments,project,command', [
    (['openspec', '--', 'list', '--json'], None, ['list', '--json']),
    (['openspec', '--', '--version'], None, ['--version']),
    (['openspec', '--version'], None, ['--version']),
    (['openspec', 'backend', '--', 'list', '--json'], 'backend', ['list', '--json']),
    (['openspec', 'backend', 'list', '--json'], 'backend', ['list', '--json']),
    (['openspec'], None, []),
])
def test_openspec_forwarding_keeps_explicit_default_separator(monkeypatch, arguments, project, command):
    seen = []
    def invoke(selected, forwarded):
        seen.append((selected, forwarded))
        return 0
    monkeypatch.setattr(harness.projects, 'openspec', invoke)
    assert harness.main(arguments) == 0
    assert seen == [(project, command)]


@pytest.mark.parametrize('arguments,project,options', [
    (['project'], None, {}),
    (['project', 'backend'], 'backend', {}),
    (['project', '--at', 'services/api'], None, {'at': 'services/api'}),
    (['project', '--at=services/api'], None, {'at': 'services/api'}),
    (['project', '--at', '.'], None, {'at': '.'}),
])
def test_project_selection_uses_directory_or_legacy_identity(monkeypatch, capsys, arguments, project, options):
    seen = []
    selected = {'id': 'existing-stable-id', 'root': 'services/api'}

    def resolve(identity, **kwargs):
        seen.append((identity, kwargs))
        return selected

    monkeypatch.setattr(harness.projects, 'resolve', resolve)
    assert harness.main(arguments) == 0
    assert seen == [(project, options)]
    assert json.loads(capsys.readouterr().out) == selected


@pytest.mark.parametrize('arguments,command,options', [
    (['openspec', '--at', 'services/api', '--', 'list', '--json'],
     ['list', '--json'], {'at': 'services/api'}),
    (['openspec', '--at=services/api', '--', 'list', '--json'],
     ['list', '--json'], {'at': 'services/api'}),
    (['openspec', '--at', '.', '--version'],
     ['--version'], {'at': '.'}),
    (['openspec', '--at', 'services/api'],
     [], {'at': 'services/api'}),
    (['openspec', '--', '--at', 'native-value'],
     ['--at', 'native-value'], {}),
    (['openspec', '--at', 'services/api', '--', 'show', 'change', '--at', 'native-value'],
     ['show', 'change', '--at', 'native-value'], {'at': 'services/api'}),
])
def test_directory_selector_preserves_upstream_argument_boundary(monkeypatch, arguments, command, options):
    seen = []

    def invoke(identity, forwarded, **kwargs):
        seen.append((identity, forwarded, kwargs))
        return 7

    monkeypatch.setattr(harness.projects, 'openspec', invoke)
    assert harness.main(arguments) == 7
    assert seen == [(None, command, options)]


@pytest.mark.parametrize('arguments', [
    ['project', 'backend', '--at', 'services/api'],
    ['project', '--at', 'services/api', 'backend'],
    ['openspec', 'backend', '--at', 'services/api', '--', 'list'],
    ['project', '--at'],
    ['openspec', '--at'],
    ['project', '--at='],
    ['openspec', '--at='],
    ['project', 'backend', 'extra'],
])
def test_invalid_selector_blocks_before_lookup_or_execution(monkeypatch, capsys, arguments):
    def unexpected(*args, **kwargs):
        pytest.fail('invalid selector reached project lookup or OpenSpec execution')

    monkeypatch.setattr(harness.projects, 'resolve', unexpected)
    monkeypatch.setattr(harness.projects, 'openspec', unexpected)
    assert harness.main(arguments) == 1
    output = capsys.readouterr()
    assert not output.out
    error = json.loads(output.err)
    assert error['status'] == 'blocked'
    assert error['reason']


def test_directory_lookup_failure_is_reported_as_blocked(monkeypatch, capsys):
    def unresolved(identity, **options):
        assert identity is None and options == {'at': 'services/api'}
        raise ValueError('nearest OpenSpec home is not registered')

    monkeypatch.setattr(harness.projects, 'resolve', unresolved)
    assert harness.main(['project', '--at', 'services/api']) == 1
    assert json.loads(capsys.readouterr().err) == {
        'status': 'blocked', 'reason': 'nearest OpenSpec home is not registered',
    }
