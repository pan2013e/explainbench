"""Durable prompt and response records for paid structured inference."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from dataset.extract_ground_truths.effect.audit_files import (
    atomic_write_json,
    atomic_write_text,
    fingerprint_file,
)


PredictionModel = TypeVar("PredictionModel", bound=BaseModel)
AUDIT_SCHEMA_VERSION = 1
PROMPT_FILENAME = "prompt.txt"
MANIFEST_FILENAME = "manifest.json"
RESPONSES_DIRECTORY = "responses"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _file_record(path: Path, *, relative_to: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "size": path.stat().st_size,
        "sha256": fingerprint_file(path),
    }


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


class PaidInferenceJournal:
    """Store one prompt and every raw response before response parsing."""

    def __init__(
        self,
        directory: str | Path,
        *,
        prompt: str,
        model_id: str,
        reasoning_effort: str,
        response_schema: str,
        resume_directories: tuple[Path, ...] = (),
    ) -> None:
        self.directory = Path(directory)
        self.responses_directory = self.directory / RESPONSES_DIRECTORY
        self.prompt_path = self.directory / PROMPT_FILENAME
        self.manifest_path = self.directory / MANIFEST_FILENAME
        self.resume_directories = resume_directories
        self.directory.mkdir(parents=True, exist_ok=True)
        self.responses_directory.mkdir(parents=True, exist_ok=True)

        prompt_bytes = prompt.encode("utf-8")
        self.request = {
            "model_id": model_id,
            "reasoning_effort": reasoning_effort,
            "response_schema": response_schema,
            "prompt": {
                "path": PROMPT_FILENAME,
                "size": len(prompt_bytes),
                "sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            },
        }
        existing = _read_json_object(self.manifest_path)
        if existing is not None and existing.get("request") != self.request:
            raise ValueError(
                "paid inference audit directory contains a different request"
            )
        atomic_write_text(self.prompt_path, prompt)
        responses = self._reconcile_responses(existing)
        self.manifest: dict[str, object] = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "request": self.request,
            "responses": responses,
            "selected_response": None,
        }
        self._write_manifest()

    def _reconcile_responses(
        self,
        existing: dict[str, object] | None,
    ) -> list[dict[str, object]]:
        existing_by_path: dict[str, dict[str, object]] = {}
        if existing is not None and existing.get("request") == self.request:
            entries = existing.get("responses")
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and isinstance(
                        entry.get("path"), str
                    ):
                        existing_by_path[entry["path"]] = entry

        records = []
        for path in sorted(self.responses_directory.glob("response-*.txt")):
            try:
                sequence = int(path.stem.removeprefix("response-"))
            except ValueError:
                continue
            record = {
                "sequence": sequence,
                **_file_record(path, relative_to=self.directory),
                "recorded_at": _now(),
            }
            previous = existing_by_path.get(record["path"])
            if (
                previous is not None
                and previous.get("size") == record["size"]
                and previous.get("sha256") == record["sha256"]
            ):
                record["recorded_at"] = previous.get("recorded_at", _now())
                if isinstance(previous.get("reused_from"), dict):
                    record["reused_from"] = previous["reused_from"]
            records.append(record)
        return records

    def _write_manifest(self) -> None:
        atomic_write_json(self.manifest_path, self.manifest)

    def record_response(
        self,
        content: str,
        *,
        reused_from: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Atomically store one exact response before it is parsed."""

        responses = self.manifest["responses"]
        if not isinstance(responses, list):
            raise RuntimeError("paid inference response journal is invalid")
        sequences = [
            item.get("sequence")
            for item in responses
            if isinstance(item, dict)
            and isinstance(item.get("sequence"), int)
            and not isinstance(item.get("sequence"), bool)
        ]
        sequence = max(sequences, default=0) + 1
        path = self.responses_directory / (
            f"response-{sequence:04d}.txt"
        )
        atomic_write_text(path, content)
        record = {
            "sequence": sequence,
            **_file_record(path, relative_to=self.directory),
            "recorded_at": _now(),
        }
        if reused_from is not None:
            record["reused_from"] = reused_from
        responses.append(record)
        self._write_manifest()
        return record

    def reuse_response(
        self,
        schema: type[PredictionModel],
    ) -> PredictionModel | None:
        """Return a compatible stored response without a new model request."""

        directories = (self.directory, *self.resume_directories)
        for directory in directories:
            manifest = _read_json_object(directory / MANIFEST_FILENAME)
            if manifest is None or manifest.get("request") != self.request:
                continue
            responses = manifest.get("responses")
            if not isinstance(responses, list):
                continue
            for response in responses:
                if not isinstance(response, dict):
                    continue
                content = self._verified_response_content(directory, response)
                if content is None:
                    continue
                try:
                    parsed = schema.model_validate_json(content)
                except ValidationError:
                    continue
                if directory == self.directory:
                    selected = response
                else:
                    source = {
                        "manifest": str(
                            (directory / MANIFEST_FILENAME).resolve()
                        ),
                        "path": response.get("path"),
                        "sha256": response.get("sha256"),
                    }
                    selected = self.record_response(
                        content,
                        reused_from=source,
                    )
                self.select_response(selected)
                return parsed
        return None

    @staticmethod
    def _verified_response_content(
        directory: Path,
        response: dict[str, object],
    ) -> str | None:
        relative_path = response.get("path")
        size = response.get("size")
        checksum = response.get("sha256")
        if (
            not isinstance(relative_path, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not isinstance(checksum, str)
        ):
            return None
        normalized = PurePosixPath(relative_path)
        if (
            normalized.is_absolute()
            or ".." in normalized.parts
            or normalized.as_posix() != relative_path
        ):
            return None
        path = directory / relative_path
        try:
            if path.stat().st_size != size:
                return None
            if fingerprint_file(path) != checksum:
                return None
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None

    def select_latest_response(self) -> dict[str, object]:
        responses = self.manifest["responses"]
        if not isinstance(responses, list) or not responses:
            raise RuntimeError("no model response is available for selection")
        selected = responses[-1]
        if not isinstance(selected, dict):
            raise RuntimeError("paid inference response journal is invalid")
        self.select_response(selected)
        return selected

    def select_response(self, response: dict[str, object]) -> None:
        self.manifest["selected_response"] = {
            "path": response["path"],
            "size": response["size"],
            "sha256": response["sha256"],
        }
        self._write_manifest()

    def selected_response(self) -> dict[str, object] | None:
        selected = self.manifest.get("selected_response")
        return dict(selected) if isinstance(selected, dict) else None
