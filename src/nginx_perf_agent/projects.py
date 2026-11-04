"""Source project registry loaded from a YAML file."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

# VCS metadata, virtualenvs, package caches and build output never hold
# analyzable source.
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "build",
        "dist",
        "htmlcov",
        "site-packages",
    }
)
EXCLUDED_FILES = ("*.pyc", "*.min.js", "*.map")


class ProjectConfigError(ValueError):
    """The registry file is missing, unreadable or invalid."""


def _endpoint_key(endpoint: str) -> str:
    """`get /x/?page=1` -> `GET /x/`; a bare path stays a path."""
    parts = endpoint.split()
    path = parts[-1].split("?", 1)[0].split("#", 1)[0]
    if len(parts) > 1 and parts[0].isalpha():
        return f"{parts[0].upper()} {path}"
    return path


class Project(BaseModel):
    """One registered source repository."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    path: Path
    enabled: bool = True
    # URL prefixes this project serves; the longest match wins.
    url_prefixes: tuple[str, ...] = ()
    # Manual endpoint mappings, `"/path/"` (any method) or `"GET /path/"`.
    endpoints: tuple[str, ...] = ()
    # Uppercase tokens in the email subject naming this project's logs,
    # e.g. ["KR", "EN", "JP"].
    subject_markers: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("project name must not be blank")
        return name

    @field_validator("subject_markers")
    @classmethod
    def _normalize_markers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        markers = tuple(marker.strip().upper() for marker in values if marker.strip())
        for marker in markers:
            if not marker.isalnum():
                raise ValueError(f"subject marker must be alphanumeric: {marker!r}")
        return markers

    @field_validator("url_prefixes")
    @classmethod
    def _check_prefixes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for prefix in values:
            if not prefix.startswith("/"):
                raise ValueError(f"URL prefix must start with '/': {prefix!r}")
        return values

    @field_validator("endpoints")
    @classmethod
    def _check_endpoints(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for endpoint in values:
            if not _endpoint_key(endpoint).split()[-1].startswith("/"):
                raise ValueError(
                    f"endpoint must look like '/path/' or 'GET /path/': {endpoint!r}"
                )
        return values


class ProjectRegistry(BaseModel):
    """All registered projects, with manual mappings resolved in one place."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    projects: tuple[Project, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> ProjectRegistry:
        names: set[str] = set()
        endpoints: dict[str, str] = {}
        markers: dict[str, str] = {}
        for project in self.projects:
            if project.name in names:
                raise ValueError(f"duplicate project name: {project.name!r}")
            names.add(project.name)
            for endpoint in project.endpoints:
                key = _endpoint_key(endpoint)
                owner = endpoints.setdefault(key, project.name)
                if owner != project.name:
                    raise ValueError(
                        f"endpoint {key!r} is mapped to both {owner!r} "
                        f"and {project.name!r}"
                    )
            for marker in project.subject_markers:
                owner = markers.setdefault(marker, project.name)
                if owner != project.name:
                    raise ValueError(
                        f"subject marker {marker!r} is claimed by both "
                        f"{owner!r} and {project.name!r}"
                    )
        return self

    @property
    def enabled_projects(self) -> tuple[Project, ...]:
        return tuple(project for project in self.projects if project.enabled)

    def missing_paths(self) -> tuple[Project, ...]:
        """Enabled projects whose checkout is absent."""
        return tuple(
            project for project in self.enabled_projects if not project.path.is_dir()
        )

    def resolve(self, endpoint: str) -> Project | None:
        """Map `"GET /api/v1/orders/?page=2"` to its project.

        Manual mappings win over URL prefixes; otherwise the longest
        matching prefix wins. `None` means no enabled project claims it.
        """
        key = _endpoint_key(endpoint)
        path = key.split()[-1]
        for project in self.enabled_projects:
            keys = {_endpoint_key(item) for item in project.endpoints}
            if key in keys or path in keys:
                return project
        best: tuple[int, Project] | None = None
        for project in self.enabled_projects:
            for prefix in project.url_prefixes:
                if path.startswith(prefix) and (
                    best is None or len(prefix) > best[0]
                ):
                    best = (len(prefix), project)
        return best[1] if best else None

    def projects_for_subject(self, subject: str) -> tuple[Project, ...]:
        """Enabled projects whose markers appear as words in the subject.

        Markers must stand alone (`EN` matches `Nginx 日志 EN`, not
        `ENVIRONMENT`); more than one match means an ambiguous subject.
        """
        tokens = set(re.findall(r"[A-Za-z0-9]+", subject.upper()))
        return tuple(
            project
            for project in self.enabled_projects
            if tokens.intersection(project.subject_markers)
        )


def load_registry(path: str | Path) -> ProjectRegistry:
    """Read and validate a registry YAML file."""
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectConfigError(f"cannot read {file}: {exc}") from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ProjectConfigError(f"invalid YAML in {file}: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectConfigError(f"{file}: expected a mapping with a 'projects' key")
    try:
        return ProjectRegistry.model_validate(data)
    except ValidationError as exc:
        raise ProjectConfigError(f"{file}: {exc}") from exc


def load_optional_registry(path: str | Path) -> ProjectRegistry | None:
    """Load the registry when the file exists; `None` disables attribution."""
    file = Path(path)
    return load_registry(file) if file.is_file() else None


def iter_source_files(
    project: Project, *, suffixes: tuple[str, ...] = (".py",)
) -> Iterator[Path]:
    """Stream analyzable files, skipping VCS, virtualenv and generated output."""
    for root, dirs, files in os.walk(project.path):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS)
        for name in sorted(files):
            if name.endswith(suffixes) and not any(
                fnmatch(name, pattern) for pattern in EXCLUDED_FILES
            ):
                yield Path(root) / name
