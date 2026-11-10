"""CLI forwarding preserves project selection and upstream argument boundaries."""
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
