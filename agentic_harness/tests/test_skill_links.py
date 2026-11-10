import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import projects
import skill_links


def test_mapping_is_finite_sorted_and_fresh():
    links = skill_links.discovery_links(['claude', 'codex'])
    assert len(links) == 6 and list(links) == sorted(links)
    assert skill_links.canonical_skill('.agents/skills/sdw-run') == 'agentic_harness/skills/sdw-run/SKILL.md'
    links.clear()
    assert len(skill_links.discovery_links(['codex'])) == 3
    for value in ('.agents/skills/sdw-run/SKILL.md', '.agents/skills/../sdw-run', '/.agents/skills/sdw-run'):
        with pytest.raises(ValueError):
            skill_links.expected_target(value)
    with pytest.raises(ValueError):
        skill_links.discovery_links(['unknown'])


def test_real_canonical_and_exact_link(tmp_path):
    relative = '.agents/skills/sdw-run'
    leaf = tmp_path / relative
    leaf.parent.mkdir(parents=True)
    canonical = tmp_path / skill_links.canonical_skill(relative)
    canonical.parent.mkdir(parents=True)
    canonical.write_text('body')
    leaf.symlink_to(skill_links.expected_target(relative), target_is_directory=True)
    assert skill_links.validate_link(tmp_path, relative) == {'kind': 'directory_symlink', 'target': '../../agentic_harness/skills/sdw-run'}
    leaf.unlink()
    leaf.symlink_to('../../agentic_harness/skills/./sdw-run')
    with pytest.raises(ValueError):
        skill_links.validate_link(tmp_path, relative)
    leaf.unlink()
    leaf.symlink_to(skill_links.expected_target(relative))
    canonical.unlink()
    canonical.symlink_to(tmp_path / 'other')
    with pytest.raises(ValueError):
        skill_links.validate_link(tmp_path, relative)


def test_alias_parent_is_rejected(tmp_path):
    (tmp_path / 'outside').mkdir()
    (tmp_path / '.agents').symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError):
        skill_links.validate_link(tmp_path, '.agents/skills/sdw-run')


def test_settings_mapping():
    assert projects.workflow_path('.') == 'agentic_harness/config/workflow.yaml'
    assert projects.workflow_path('services/api') == 'agentic_harness/config/services/api/workflow.yaml'
    assert projects.workflow_path('services/api', 2) == 'services/api/openspec/workflow.yaml'
    with pytest.raises(ValueError):
        projects.workflow_path('../api')


@pytest.mark.parametrize('relative,target', list(skill_links.discovery_links(['codex', 'claude']).items()))
def test_every_approved_leaf_checks_its_own_canonical_skill(tmp_path, relative, target):
    leaf = tmp_path / relative; leaf.parent.mkdir(parents=True)
    canonical = tmp_path / skill_links.canonical_skill(relative)
    canonical.parent.mkdir(parents=True); canonical.write_text('canonical')
    leaf.symlink_to(target)
    assert skill_links.validate_link(tmp_path, relative) == {'kind': 'directory_symlink', 'target': target}
    canonical.unlink()
    with pytest.raises(ValueError, match='missing or unsafe'):
        skill_links.validate_link(tmp_path, relative)


@pytest.mark.parametrize('kind', ['regular', 'directory', 'absolute-target', 'canonical-directory-alias'])
def test_nonapproved_types_and_aliases_fail(tmp_path, kind):
    relative = '.agents/skills/sdw-run'
    leaf = tmp_path / relative; leaf.parent.mkdir(parents=True)
    canonical = tmp_path / skill_links.canonical_skill(relative)
    canonical.parent.mkdir(parents=True); canonical.write_text('body')
    if kind == 'regular':
        leaf.write_text('body')
    elif kind == 'directory':
        leaf.mkdir()
    else:
        leaf.symlink_to(canonical.parent if kind == 'absolute-target' else skill_links.expected_target(relative))
        if kind == 'canonical-directory-alias':
            canonical.unlink(); canonical.parent.rmdir()
            other = tmp_path / 'other'; other.mkdir(); (other / 'SKILL.md').write_text('body')
            canonical.parent.symlink_to(other)
    with pytest.raises(ValueError):
        skill_links.validate_link(tmp_path, relative)
