"""Checksummed manifests for stage outputs stored outside result JSON files."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from explainbench.question_builders.common.fingerprints import fingerprint_file
from explainbench.schemas import StrictModel


class ArtifactFile(StrictModel):
    """One regular file relative to an artifact-manifest root."""

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        _validate_relative_path(value, label="artifact file path")
        return value


class ArtifactManifest(StrictModel):
    """Portable file inventory rooted at one stage-instance directory."""

    schema_version: Literal[1] = 1
    root: str
    files: list[ArtifactFile]

    @field_validator("root")
    @classmethod
    def validate_root(cls, value: str) -> str:
        _validate_relative_path(value, label="artifact root")
        return value

    @model_validator(mode="after")
    def validate_unique_sorted_files(self):
        paths = [item.path for item in self.files]
        if paths != sorted(set(paths)):
            raise ValueError("artifact files must be sorted and unique")
        return self


def _validate_relative_path(value: str, *, label: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a safe relative path")
    if value != path.as_posix():
        raise ValueError(f"{label} must use normalized POSIX separators")


def build_artifact_manifest(
    artifact_root: Path,
    *,
    relative_to: Path,
) -> ArtifactManifest:
    """Inventory all regular files under an artifact directory."""

    root = artifact_root.resolve()
    base = relative_to.resolve()
    try:
        relative_root = root.relative_to(base).as_posix()
    except ValueError as error:
        raise ValueError(
            f"artifact root {root} is outside stage instance directory {base}"
        ) from error
    if not root.is_dir():
        raise ValueError(f"artifact root is not a directory: {root}")

    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        files.append(
            ArtifactFile(
                path=path.relative_to(root).as_posix(),
                size=path.stat().st_size,
                sha256=fingerprint_file(path),
            )
        )
    return ArtifactManifest(root=relative_root, files=files)


def validate_artifact_manifest(
    value: object,
    *,
    relative_to: Path,
) -> ArtifactManifest:
    """Validate a manifest and verify every recorded file on disk."""

    manifest = ArtifactManifest.model_validate(value)
    base = relative_to.resolve()
    root = (base / PurePosixPath(manifest.root)).resolve()
    try:
        root.relative_to(base)
    except ValueError as error:
        raise ValueError(
            "artifact root resolves outside stage instance directory"
        ) from error
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"artifact root is missing or invalid: {root}")

    current_paths = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    recorded_paths = [item.path for item in manifest.files]
    if current_paths != recorded_paths:
        raise ValueError("artifact files do not match the recorded manifest")

    for item in manifest.files:
        path = root / PurePosixPath(item.path)
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"artifact file is missing or invalid: {path}")
        if path.stat().st_size != item.size:
            raise ValueError(f"artifact file size changed: {path}")
        if fingerprint_file(path) != item.sha256:
            raise ValueError(f"artifact file checksum changed: {path}")
    return manifest
