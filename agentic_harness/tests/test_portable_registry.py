"""Whole-project and partial-domain routing stays unambiguous after manual edits."""
import json
from types import SimpleNamespace

import pytest
import yaml

from test_isolation import projects, registered, entry, save_registry, write


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


def local_settings(root, data):
    """Migrate a fixture without changing its stored runtime identities."""
    bindings = {}
    for name, project in data['projects'].items():
        settings = {key: value for key, value in project.items() if key not in {'root', 'queue'}}
        write(root / project['root'] / 'openspec/workflow.yaml',
              yaml.safe_dump({'schema_version': 1, **settings}))
        bindings[name] = {'root': project['root']}
    save_registry(root, {'schema_version': 2, 'projects': bindings})


def test_local_configuration_preserves_legacy_runtime_identity_and_authority(registered):
    root, data = registered
    original = data['projects']['service']
    original['environment'] = {'lockfiles': ['package-lock.json'], 'prepare': [['npm', 'ci']]}
    original['evidence_exclude'] = ['private']
    save_registry(root, data)
    before = projects.resolve('service', root)
    assert projects.configuration_paths(root, before) == ['agentic_harness/projects.yaml']

    local_settings(root, data)
    selected = projects.resolve(None, root, at='packages/service')
    assert selected == before
    assert projects.configuration_paths(root, selected) == [
        'agentic_harness/projects.yaml', 'packages/service/openspec/workflow.yaml',
    ]
    assert projects.resolve('service', root, cwd=root / 'elsewhere') == before


def test_optional_defaults_normalize_identically_in_both_formats(registered):
    root, data = registered
    before = projects.registry(root)
    local_settings(root, data)
    assert projects.registry(root) == before


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('keep_current', [False, True], ids=['legacy-only', 'dual-index'])
def test_current_runtime_requires_one_canonical_directory_authority(registered, version, keep_current):
    root, data = registered
    if version == 2:
        local_settings(root, data)
    current = root / 'agentic_harness/projects.yaml'
    legacy = write(root / '_agentic_harness/projects.yaml', current.read_text())
    if not keep_current:
        current.unlink()
    original = legacy.read_bytes()
    with pytest.raises(ValueError, match='ambiguous workflow authority|legacy workflow directory'):
        projects.resolve('service', root)
    assert legacy.read_bytes() == original


def test_legacy_cache_directory_without_authority_does_not_block_current_runtime(registered):
    root, _ = registered
    write(root / '_agentic_harness/local-notes.md', 'Retained local notes.\n')
    write(root / '_agentic_harness/node_modules/.cache/retained', 'cache\n')
    assert projects.resolve('service', root)['id'] == 'service'


def test_local_settings_are_the_only_executable_authority(registered):
    root, data = registered
    local_settings(root, data)
    path = root / 'packages/service/openspec/workflow.yaml'
    settings = yaml.safe_load(path.read_text())
    settings['checks'] = [['node', 'verify.mjs']]
    settings['code_roots'] = ['packages/service', 'tests/service']
    path.write_text(yaml.safe_dump(settings))
    selected = projects.resolve('service', root)
    assert selected['checks'] == [['node', 'verify.mjs']]
    assert selected['code_roots'] == ['packages/service', 'tests/service']


@pytest.mark.parametrize('content', [
    '[]\n', 'schema_version: 1\nchecks: [[node, --test]]\n',
    'schema_version: 2\ncode_roots: [packages/service]\nchecks: [[node, --test]]\n',
    'schema_version: true\ncode_roots: [packages/service]\nchecks: [[node, --test]]\n',
    'schema_version: 1\ncode_roots: []\nchecks: [[node, --test]]\n',
    'schema_version: 1\ncode_roots: [../outside]\nchecks: [[node, --test]]\n',
    'schema_version: 1\ncode_roots: [packages/service]\nchecks: []\n',
    'schema_version: 1\ncode_roots: [packages/service]\nchecks: npm test\n',
    'schema_version: 1\ncode_roots: [packages/service]\nchecks: [[node, --test]]\nunknown: true\n',
    'schema_version: 1\ncode_roots: [packages/service]\nchecks: [[node, --test]]\nchecks: []\n',
    'schema_version: 1\ncode_roots: [\n',
])
def test_invalid_local_configuration_never_falls_back_to_defaults(registered, content):
    root, data = registered
    local_settings(root, data)
    path = root / 'packages/service/openspec/workflow.yaml'
    path.write_text(content)
    with pytest.raises(ValueError):
        projects.resolve('service', root)
    assert path.read_text() == content


@pytest.mark.parametrize('kind', ['missing', 'symlink'])
def test_missing_or_aliased_local_authority_blocks(registered, tmp_path, kind):
    root, data = registered
    local_settings(root, data)
    path = root / 'packages/service/openspec/workflow.yaml'
    content = path.read_text()
    path.unlink()
    if kind == 'symlink':
        external = write(tmp_path / 'outside-workflow.yaml', content)
        path.symlink_to(external)
    with pytest.raises(ValueError, match='missing registered path|aliased path'):
        projects.registry(root)


def test_index_cannot_supply_a_second_copy_of_local_checks(registered):
    root, data = registered
    local_settings(root, data)
    save_registry(root, {'schema_version': 2, 'projects': {
        'service': {'root': 'packages/service', 'checks': [['true']]},
    }})
    with pytest.raises(ValueError, match='invalid project'):
        projects.registry(root)


def test_legacy_and_companion_must_agree_before_migration(registered):
    root, data = registered
    before = projects.registry(root)
    local_settings(root, data)
    save_registry(root, data)
    assert projects.registry(root) == before
    path = root / 'packages/service/openspec/workflow.yaml'
    settings = yaml.safe_load(path.read_text())
    settings['checks'] = [['true']]
    path.write_text(yaml.safe_dump(settings))
    with pytest.raises(ValueError, match='conflicting legacy and local'):
        projects.registry(root)


def test_v2_still_rejects_overlapping_scopes(registered):
    root, data = registered
    data['projects']['other'] = entry(root, 'packages/other')
    data['projects']['other']['code_roots'] = ['packages']
    local_settings(root, data)
    with pytest.raises(ValueError, match='overlapping project areas'):
        projects.registry(root)


def test_directory_selection_and_cwd_choose_same_nearest_home(registered):
    root, data = registered
    data['projects']['other'] = entry(root, 'packages/other')
    nested = root / 'packages/service/src/deep'
    nested.mkdir(parents=True)
    local_settings(root, data)
    selected = projects.resolve(None, root, at='packages/service/src/deep')
    assert selected['id'] == 'service'
    assert projects.resolve(None, root, cwd=nested) == selected
    assert projects.resolve('other', root, cwd=nested)['root'] == 'packages/other'
    with pytest.raises(ValueError, match='multiple registered projects'):
        projects.resolve(None, root, cwd=root)


@pytest.mark.parametrize('version', [1, 2])
def test_sole_fallback_applies_only_when_no_native_home_is_found(registered, version):
    root, data = registered
    if version == 2:
        local_settings(root, data)
    unrelated = root / 'tests/service'
    unrelated.mkdir(parents=True)
    assert projects.resolve(None, root, cwd=unrelated)['id'] == 'service'
    with pytest.raises(ValueError, match='no OpenSpec home'):
        projects.resolve(None, root, at='tests/service')
    write(root / 'tests/service/openspec/config.yaml', 'schema: spec-driven\n')
    with pytest.raises(ValueError, match='nearest OpenSpec home is not adopted'):
        projects.resolve(None, root, cwd=unrelated)


@pytest.mark.parametrize('marker', ['config.yaml', 'config.yml', 'specs', 'changes'])
def test_nearer_unadopted_native_root_blocks_parent_selection(registered, marker):
    root, data = registered
    local_settings(root, data)
    nested = root / 'packages/service/nested'
    marker_path = nested / 'openspec' / marker
    if marker.endswith('.yaml') or marker.endswith('.yml'):
        write(marker_path, 'schema: spec-driven\n')
    else:
        marker_path.mkdir(parents=True)
    with pytest.raises(ValueError, match='nearest OpenSpec home is not adopted'):
        projects.resolve(None, root, at='packages/service/nested')
    with pytest.raises(ValueError, match='nearest OpenSpec home is not adopted'):
        projects.resolve(None, root, cwd=nested)
    assert projects.resolve('service', root, cwd=nested)['root'] == 'packages/service'


@pytest.mark.parametrize('at', ['', '../outside', '/outside', 'packages/../packages/service',
                               'packages/service/', 'packages/service/openspec/config.yaml', 'missing'])
def test_invalid_directory_selector_cannot_trigger_sole_fallback(registered, at):
    root, _ = registered
    with pytest.raises(ValueError):
        projects.resolve(None, root, at=at)


def test_directory_alias_cannot_select_an_open_spec_home(registered):
    root, _ = registered
    (root / 'alias').symlink_to(root / 'packages/service', target_is_directory=True)
    with pytest.raises(ValueError, match='aliased'):
        projects.resolve(None, root, at='alias')


@pytest.mark.parametrize('arguments', [
    ['list', '--store', 'team-plans'], ['list', '--store=team-plans'],
    ['list', '--store-path', '/outside'], ['list', '--store-path=/outside'],
])
def test_external_store_flags_cannot_override_selected_home(registered, monkeypatch, arguments):
    root, _ = registered
    monkeypatch.setattr(projects.subprocess, 'run', lambda *args, **kwargs: pytest.fail('must not launch OpenSpec'))
    with pytest.raises(ValueError, match='store selectors cannot override'):
        projects.openspec(None, arguments, root, at='packages/service')


@pytest.mark.parametrize('filename', ['config.yaml', 'config.yml'])
def test_native_store_pointer_cannot_redirect_local_runtime(registered, filename):
    root, _ = registered
    home = root / 'packages/service/openspec'
    (home / 'config.yaml').unlink()
    write(home / filename, 'schema: spec-driven\nstore: team-plans\n')
    with pytest.raises(ValueError, match='external OpenSpec stores'):
        projects.resolve('service', root)


def test_read_only_native_references_preserve_local_home(registered):
    root, _ = registered
    write(root / 'packages/service/openspec/config.yaml',
          'schema: spec-driven\nreferences: [team-plans]\n')
    assert projects.resolve('service', root)['root'] == 'packages/service'


def test_local_openspec_forwarding_preserves_commands_and_selected_cwd(registered, monkeypatch):
    root, _ = registered
    write(root / 'agentic_harness/node_modules/.bin/openspec', 'placeholder\n')
    write(root / 'agentic_harness/package.json', json.dumps({'dependencies': {'@fission-ai/openspec': '1.14.3'}}))
    launcher = write(root / 'agentic_harness/tools/openspec.mjs', 'placeholder\n')
    seen = []

    def invoke(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=6)

    monkeypatch.setattr(projects.subprocess, 'run', invoke)
    assert projects.openspec(None, ['show', 'change', '--json'], root, at='packages/service') == 6
    assert len(seen) == 1
    assert seen[0][0] == ['node', str(launcher), 'show', 'change', '--json']
    assert seen[0][1]['cwd'] == root / 'packages/service'
    assert seen[0][1]['env']['OPENSPEC_TELEMETRY'] == '0'


def harness_settings(root, data):
    bindings = {}
    for name, project in data['projects'].items():
        settings = {key: value for key, value in project.items() if key not in {'root', 'queue'}}
        write(root / projects.workflow_path(project['root']), yaml.safe_dump({'schema_version': 1, **settings}))
        (root / project['queue']).rename(root / project['root'] / 'openspec/dependency-map.yaml')
        bindings[name] = {'root': project['root']}
    save_registry(root, {'schema_version': 3, 'projects': bindings})


def test_schema_three_reports_exact_settings_authority_and_eligibility(registered):
    root, data = registered
    harness_settings(root, data)
    selected = projects.resolve(None, root, at='packages/service')
    path = 'agentic_harness/config/packages/service/workflow.yaml'
    assert selected['workflow'] == path
    assert selected['queue'] == 'packages/service/openspec/dependency-map.yaml'
    assert projects.configuration_paths(root, selected) == ['agentic_harness/projects.yaml', path]
    areas = projects.editable_areas(selected)
    assert path in areas
    assert not any(projects.scope_contains(area, 'agentic_harness/config/neighbor/workflow.yaml') for area in areas)
    assert not any(projects.scope_contains(area, 'agentic_harness/skills/sdw-run/SKILL.md') for area in areas)


@pytest.mark.parametrize('alternate', ['packages/service/openspec/workflow.yaml', 'packages/service/openspec/queue.yaml'])
def test_schema_three_rejects_equivalent_legacy_authority(registered, alternate):
    root, data = registered
    harness_settings(root, data)
    write(root / alternate, 'queue: []\n')
    with pytest.raises(ValueError, match='ambiguous workflow authority'):
        projects.resolve('service', root)


@pytest.mark.parametrize('version', [1, 2])
def test_old_schema_rejects_new_settings_even_when_equivalent(registered, version):
    root, data = registered
    if version == 2:
        local_settings(root, data)
    write(root / projects.workflow_path('packages/service'), 'schema_version: 1\n')
    with pytest.raises(ValueError, match='ambiguous workflow authority'):
        projects.resolve('service', root)


def test_schema_three_settings_scope_cannot_be_absorbed_by_neighbor(registered):
    root, data = registered
    data['projects']['other'] = entry(root, 'other')
    data['projects']['other']['code_roots'] = ['agentic_harness/config/packages/service']
    harness_settings(root, data)
    with pytest.raises(ValueError, match='overlapping project areas'):
        projects.registry(root)


@pytest.mark.parametrize('authority', ['workflow', 'queue'])
def test_schema_three_missing_required_authority_fails_closed(registered, authority):
    root, data = registered
    harness_settings(root, data)
    selected = projects.resolve('service', root)
    (root / selected[authority]).unlink()
    with pytest.raises(ValueError, match='missing registered path'):
        projects.registry(root)


@pytest.mark.parametrize('home', ['.', 'services/api space'])
def test_schema_three_root_and_spaced_component_keep_settings_semantics(tmp_path, home):
    root = tmp_path / 'repo'
    binding = entry(root, home)
    binding.update(environment={'lockfiles': ['lock file.json'], 'prepare': [['node', 'prepare script.js']]},
                   evidence_exclude=['private records'])
    data = {'schema_version': 1, 'projects': {'stable_id': binding}}
    save_registry(root, data)
    before = projects.resolve('stable_id', root)
    harness_settings(root, data)
    selected = projects.resolve(None, root, at=home)
    assert selected['id'] == 'stable_id' and selected['root'] == home
    for field in ('code_roots', 'checks', 'environment', 'evidence_exclude'):
        assert selected[field] == before[field]
    assert selected['workflow'] == projects.workflow_path(home)
    assert projects.resolve('stable_id', root, cwd=root) == selected


@pytest.mark.parametrize('home', ['.', 'services/api'])
@pytest.mark.parametrize('document', [
    'queue: [\n', '[]\n', 'queue: {}\n', 'queue: []\nextra: true\n',
    'queue: [wrong]\n', 'queue: [{change: first}]\n',
    'queue: [{change: first, depends_on: [], extra: true}]\n',
    'queue: [{change: first, depends_on: []}, {change: first, depends_on: []}]\n',
    'queue: [{change: first, depends_on: []}, {change: next, depends_on: [first, first]}]\n',
    'queue: [{change: first, depends_on: [later]}, {change: later, depends_on: []}]\n',
    'queue: [{change: first, depends_on: [first]}]\n',
    'queue: [{change: first, depends_on: [next]}, {change: next, depends_on: [first]}]\n',
    'queue: []\nqueue: []\n', 'queue: &entries []\n',
    'queue: [{change: first, depends_on: [[invalid]]}]\n',
])
def test_schema_three_selection_validates_dependency_document(tmp_path, home, document):
    root = tmp_path / 'repo'
    data = {'schema_version': 1, 'projects': {'service': entry(root, home)}}
    save_registry(root, data)
    harness_settings(root, data)
    authority = (root / home / 'openspec/dependency-map.yaml')
    authority.write_text(document)
    with pytest.raises(ValueError) as error:
        projects.resolve(None, root, at=home)
    assert authority.relative_to(root).as_posix() in str(error.value)


@pytest.mark.parametrize('document', [
    'queue: []\n',
    'queue: [{change: absent-first, depends_on: []}, {change: absent-next, depends_on: [absent-first]}]\n',
])
def test_schema_three_selection_only_validates_document_not_readiness(registered, document):
    root, data = registered
    harness_settings(root, data)
    authority = root / 'packages/service/openspec/dependency-map.yaml'
    authority.write_text(document)
    before = authority.read_bytes()
    assert projects.resolve('service', root)['queue'] == authority.relative_to(root).as_posix()
    assert authority.read_bytes() == before


@pytest.mark.parametrize('version', [1, 2])
def test_legacy_selection_does_not_gain_execution_readiness_checks(registered, version):
    root, data = registered
    if version == 2:
        local_settings(root, data)
    write(root / 'packages/service/openspec/queue.yaml', 'legacy-unparsed-document\n')
    assert projects.resolve('service', root)['queue'] == 'packages/service/openspec/queue.yaml'


@pytest.mark.parametrize('authority', ['workflow', 'queue'])
@pytest.mark.parametrize('replacement', ['missing', 'symlink', 'directory'])
def test_schema_three_authority_kind_errors_name_exact_selected_path(registered, tmp_path, authority, replacement):
    root, data = registered
    harness_settings(root, data)
    selected = projects.resolve('service', root)
    relative = selected[authority]
    path = root / relative
    payload = path.read_bytes()
    path.unlink()
    if replacement == 'symlink':
        external = tmp_path / 'external-authority.yaml'
        external.write_bytes(payload)
        path.symlink_to(external)
    elif replacement == 'directory':
        path.mkdir()
    with pytest.raises(ValueError) as error:
        projects.resolve('service', root)
    assert relative in str(error.value)


@pytest.mark.parametrize('home', ['.', 'services/api'])
@pytest.mark.parametrize('field,value,cause', [
    ('checks', [], 'checks must be argv arrays'),
    ('code_roots', [], 'invalid code roots'),
    ('environment', {'prepare': 'not argv'}, 'environment prepare must be argv arrays'),
    ('evidence_exclude', 'not paths', 'invalid evidence exclusions'),
    ('environment', 'not mapping', 'invalid environment'),
    ('checks', ['npm test'], 'checks must be argv arrays'),
    ('environment', {'prepare': ['npm install']}, 'environment prepare must be argv arrays'),
    ('code_roots', ['../outside'], 'unsafe path: ../outside'),
    ('environment', {'lockfiles': ['../outside.lock']}, 'unsafe path: ../outside.lock'),
    ('evidence_exclude', ['../outside'], 'unsafe path: ../outside'),
])
def test_current_settings_semantic_errors_retain_authority_and_cause(tmp_path, home, field, value, cause):
    root = tmp_path / 'repo'
    data = {'schema_version': 1, 'projects': {'service': entry(root, home)}}
    save_registry(root, data)
    harness_settings(root, data)
    relative = projects.workflow_path(home)
    path = root / relative
    settings = yaml.safe_load(path.read_text())
    settings[field] = value
    path.write_text(yaml.safe_dump(settings))
    with pytest.raises(ValueError) as error:
        projects.resolve(None, root, at=home)
    assert type(error.value) is ValueError
    assert relative in str(error.value) and cause in str(error.value)
    assert isinstance(error.value.__cause__, ValueError)
    assert cause in str(error.value.__cause__)


@pytest.mark.parametrize('home', ['.', 'services/api'])
@pytest.mark.parametrize('payload,cause', [
    (b'checks: [\n', 'invalid YAML configuration'),
    (b'checks: []\nchecks: []\n', 'duplicate configuration key: checks'),
    (b'\xff\xfe', 'invalid YAML configuration'),
])
def test_current_settings_decoding_errors_retain_authority_and_chain(tmp_path, home, payload, cause):
    root = tmp_path / 'repo'
    data = {'schema_version': 1, 'projects': {'service': entry(root, home)}}
    save_registry(root, data)
    harness_settings(root, data)
    relative = projects.workflow_path(home)
    (root / relative).write_bytes(payload)
    with pytest.raises(ValueError) as error:
        projects.resolve('service', root)
    assert relative in str(error.value) and cause in str(error.value)
    assert isinstance(error.value.__cause__, ValueError)


@pytest.mark.parametrize('home', ['.', 'services/api'])
@pytest.mark.parametrize('version', [1, 2])
def test_legacy_semantic_errors_name_the_actual_settings_authority(tmp_path, home, version):
    root = tmp_path / 'repo'
    data = {'schema_version': 1, 'projects': {'service': entry(root, home)}}
    if version == 1:
        data['projects']['service']['checks'] = []
        save_registry(root, data)
        authority = projects.INDEX_PATH
    else:
        local_settings(root, data)
        authority = projects.workflow_path(home, 2)
        settings = yaml.safe_load((root / authority).read_text())
        settings['checks'] = []
        (root / authority).write_text(yaml.safe_dump(settings))
    with pytest.raises(ValueError) as error:
        projects.resolve('service', root)
    assert authority in str(error.value) and 'checks must be argv arrays' in str(error.value)
    assert projects.workflow_path(home, 3) not in str(error.value)


@pytest.mark.parametrize('home', ['.', 'services/api'])
def test_invalid_legacy_companion_is_not_attributed_to_inline_settings(tmp_path, home):
    root = tmp_path / 'repo'
    data = {'schema_version': 1, 'projects': {'service': entry(root, home)}}
    save_registry(root, data)
    authority = projects.workflow_path(home, 2)
    write(root / authority, yaml.safe_dump({'schema_version': 1, 'code_roots': [home], 'checks': []}))
    with pytest.raises(ValueError) as error:
        projects.resolve('service', root)
    assert authority in str(error.value) and 'checks must be argv arrays' in str(error.value)
    assert projects.INDEX_PATH not in str(error.value)
