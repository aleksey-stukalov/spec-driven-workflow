"""Whole-project and partial-domain routing stays unambiguous after manual edits."""
import pytest

from test_isolation import projects, registered, entry, save_registry


def test_existing_yml_configuration_keeps_its_name(registered):
    root, data = registered
    home = root / data['projects']['service']['root'] / 'openspec'
    (home / 'config.yaml').rename(home / 'config.yml')
    selected = projects.resolve(None, root)
    assert projects.config_path(root, selected) == home / 'config.yml'
    assert not (home / 'config.yaml').exists()


def test_competing_config_filenames_are_not_silently_selected(registered):
    root, data = registered
    home = root / data['projects']['service']['root'] / 'openspec'
    (home / 'config.yml').write_text('schema: spec-driven\n')
    with pytest.raises(ValueError, match='exactly one'):
        projects.resolve(None, root)


def test_configuration_symlink_is_not_an_authority(registered, tmp_path):
    root, data = registered
    target = tmp_path / 'outside.yml'
    target.write_text('schema: spec-driven\n')
    config = root / data['projects']['service']['root'] / 'openspec/config.yaml'
    config.unlink(); config.symlink_to(target)
    with pytest.raises(ValueError, match='aliased'):
        projects.registry(root)


@pytest.mark.parametrize('other_root', ['.', 'packages/service/nested'])
def test_overlapping_project_roots_are_rejected_after_manual_edit(registered, other_root):
    root, data = registered
    data['projects']['other'] = entry(root, other_root)
    data['projects']['other']['code_roots'] = ['unrelated']
    save_registry(root, data)
    with pytest.raises(ValueError, match='overlapping project roots'):
        projects.registry(root)


@pytest.mark.parametrize('other_scope', ['packages', 'packages/service', 'packages/service/api', '.'])
def test_overlapping_domain_code_roots_are_rejected(registered, other_scope):
    root, data = registered
    data['projects']['other'] = entry(root, 'other')
    data['projects']['other']['code_roots'] = [other_scope]
    save_registry(root, data)
    with pytest.raises(ValueError, match='overlapping project areas'):
        projects.registry(root)


def test_metadata_cannot_be_application_scope_of_another_domain(registered):
    root, data = registered
    data['projects']['service']['code_roots'] = ['application']
    data['projects']['other'] = entry(root, 'other')
    data['projects']['other']['code_roots'] = ['packages/service/openspec']
    save_registry(root, data)
    with pytest.raises(ValueError, match='overlapping project areas'):
        projects.registry(root)


def test_root_planning_home_does_not_expand_domain_application_scope(tmp_path):
    root = tmp_path / 'repo'
    selected = entry(root, '.')
    selected['code_roots'] = ['apps/api', 'tests/api']
    save_registry(root, {'schema_version': 1, 'projects': {'api': selected}})
    actual = projects.resolve('api', root)
    assert projects.editable_areas(actual) == ['apps/api', 'tests/api', 'openspec']
    assert not any(projects.scope_contains(area, 'README.md') for area in projects.editable_areas(actual))
