"""Finite SDW discovery links; never a general alias-following path resolver."""
from __future__ import annotations

import os
import stat
from pathlib import Path

_PROVIDERS = {'codex': '.agents', 'claude': '.claude'}
_NAMES = ('sdw-harden', 'sdw-review', 'sdw-run')


def discovery_links(agents):
    """Return the selected exact discovery leaves and literal relative targets."""
    agents = list(agents)
    if any(agent not in _PROVIDERS for agent in agents):
        raise ValueError('unknown skill provider')
    return dict(sorted((f'{_PROVIDERS[agent]}/skills/{name}',
                        f'../../agentic_harness/skills/{name}')
                       for agent in agents for name in _NAMES))


def expected_target(relative):
    try:
        return discovery_links(_PROVIDERS)[relative]
    except (KeyError, TypeError) as exc:
        raise ValueError(f'not an approved discovery link: {relative}') from exc


def canonical_skill(relative):
    expected_target(relative)
    return f'agentic_harness/skills/{relative.rsplit("/", 1)[1]}/SKILL.md'


def _real_parents(root, relative):
    """Inspect every existing ancestor lexically, without dereferencing links."""
    current = Path(root)
    if not stat.S_ISDIR(current.lstat().st_mode):
        raise ValueError('skill root must be a real directory')
    for component in Path(relative).parts[:-1]:
        current = current / component
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise ValueError(f'non-directory or aliased skill ancestor: {current}')


def validate_link(root, relative):
    target = expected_target(relative)
    root = Path(root)
    try:
        _real_parents(root, relative)
        leaf = root / relative
        if not stat.S_ISLNK(leaf.lstat().st_mode) or os.readlink(leaf) != target:
            raise ValueError(f'invalid discovery link: {relative}')
        canonical = canonical_skill(relative)
        _real_parents(root, canonical)
        if not stat.S_ISREG((root / canonical).lstat().st_mode):
            raise ValueError(f'canonical skill must be a regular file: {canonical}')
    except OSError as exc:
        raise ValueError(f'missing or unsafe discovery link: {relative}') from exc
    return {'kind': 'directory_symlink', 'target': target}
