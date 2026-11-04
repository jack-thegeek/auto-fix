import pytest

from nginx_perf_agent.projects import (
    Project,
    ProjectConfigError,
    iter_source_files,
    load_registry,
)


def write_registry(tmp_path, text: str):
    path = tmp_path / "projects.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_projects_with_defaults(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = write_registry(
        tmp_path,
        f"projects:\n  - name: demo\n    path: {repo}\n",
    )

    registry = load_registry(path)

    project = registry.projects[0]
    assert project.name == "demo"
    assert project.path == repo
    assert project.enabled is True
    assert project.url_prefixes == ()
    assert project.endpoints == ()


def test_duplicate_names_rejected(tmp_path):
    path = write_registry(
        tmp_path,
        "projects:\n"
        "  - name: demo\n    path: /a\n"
        "  - name: demo\n    path: /b\n",
    )

    with pytest.raises(ProjectConfigError, match="duplicate project name"):
        load_registry(path)


def test_prefix_must_start_with_slash(tmp_path):
    path = write_registry(
        tmp_path,
        "projects:\n  - name: demo\n    path: /a\n    url_prefixes: ['api/']\n",
    )

    with pytest.raises(ProjectConfigError, match="must start with '/'"):
        load_registry(path)


def test_endpoint_must_be_a_path(tmp_path):
    path = write_registry(
        tmp_path,
        "projects:\n  - name: demo\n    path: /a\n    endpoints: ['orders']\n",
    )

    with pytest.raises(ProjectConfigError, match="must look like"):
        load_registry(path)


def test_unknown_key_rejected(tmp_path):
    path = write_registry(
        tmp_path,
        f"projects:\n  - name: demo\n    path: {tmp_path}\n    url_prefix: ['/x/']\n",
    )

    with pytest.raises(ProjectConfigError):
        load_registry(path)


def test_missing_file_and_invalid_yaml_rejected(tmp_path):
    with pytest.raises(ProjectConfigError, match="cannot read"):
        load_registry(tmp_path / "absent.yaml")

    path = write_registry(tmp_path, "projects: [\n")
    with pytest.raises(ProjectConfigError, match="invalid YAML"):
        load_registry(path)


def test_resolve_prefers_manual_mapping_then_longest_prefix(tmp_path):
    registry = load_registry(
        write_registry(
            tmp_path,
            "projects:\n"
            "  - name: api\n"
            "    path: /a\n"
            "    url_prefixes: ['/api/']\n"
            "    endpoints: ['GET /legacy/']\n"
            "  - name: api-v2\n"
            "    path: /b\n"
            "    url_prefixes: ['/api/v2/']\n",
        )
    )

    assert registry.resolve("GET /legacy/?x=1").name == "api"
    assert registry.resolve("POST /legacy/") is None
    assert registry.resolve("GET /api/v2/orders/").name == "api-v2"
    assert registry.resolve("POST /api/orders/").name == "api"
    assert registry.resolve("GET /elsewhere/") is None


def test_disabled_projects_are_ignored(tmp_path):
    registry = load_registry(
        write_registry(
            tmp_path,
            "projects:\n"
            "  - name: disabled-site\n"
            "    path: /a\n"
            "    enabled: false\n"
            "    url_prefixes: ['/api/']\n",
        )
    )

    assert registry.enabled_projects == ()
    assert registry.resolve("GET /api/orders/") is None


def test_duplicate_endpoint_mapping_rejected(tmp_path):
    path = write_registry(
        tmp_path,
        "projects:\n"
        "  - name: a\n    path: /a\n    endpoints: ['/shared/']\n"
        "  - name: b\n    path: /b\n    endpoints: ['/shared/']\n",
    )

    with pytest.raises(ProjectConfigError, match="mapped to both"):
        load_registry(path)


def test_missing_paths_only_reports_enabled(tmp_path):
    registry = load_registry(
        write_registry(
            tmp_path,
            "projects:\n"
            f"  - name: present\n    path: {tmp_path}\n"
            "  - name: gone\n    path: /does/not/exist\n"
            "  - name: ignored\n    path: /does/not/exist\n    enabled: false\n",
        )
    )

    assert [project.name for project in registry.missing_paths()] == ["gone"]


def test_iter_source_files_skips_vcs_virtualenvs_and_generated(tmp_path):
    for name in ("app.py", "main.py"):
        (tmp_path / name).write_text("")
    for directory in (".git", ".venv", "node_modules", "__pycache__", "build"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "hidden.py").write_text("")
    (tmp_path / "bundle.min.js").write_text("")

    project = Project(name="demo", path=tmp_path, enabled=True)
    found = [path.name for path in iter_source_files(project, suffixes=(".py", ".js"))]

    assert found == ["app.py", "main.py"]


def test_subject_markers_resolve_project_and_flag_ambiguity(tmp_path):
    registry = load_registry(
        write_registry(
            tmp_path,
            "projects:\n"
            "  - name: vb-en\n"
            "    path: /a\n"
            "    subject_markers: [kr, EN, JP]\n"
            "  - name: vb-cn\n"
            "    path: /b\n"
            "    subject_markers: [CN]\n",
        )
    )

    def names(subject):
        return [project.name for project in registry.projects_for_subject(subject)]

    assert names("Nginx 日志 KR 2026-10-10") == ["vb-en"]
    assert names("nginx 日志 en") == ["vb-en"]
    assert names("Nginx 日志 JP") == ["vb-en"]
    assert names("Nginx 日志 CN") == ["vb-cn"]
    assert names("Nginx 日志") == []
    assert names("Nginx 日志 ENVIRONMENT") == []
    assert names("Nginx 日志 EN CN") == ["vb-en", "vb-cn"]


def test_duplicate_subject_marker_rejected(tmp_path):
    path = write_registry(
        tmp_path,
        "projects:\n"
        "  - name: a\n    path: /a\n    subject_markers: [EN]\n"
        "  - name: b\n    path: /b\n    subject_markers: [EN]\n",
    )

    with pytest.raises(ProjectConfigError, match="subject marker"):
        load_registry(path)
