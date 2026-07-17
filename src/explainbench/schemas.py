"""Pydantic models for ExplainBench submissions."""

from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model that rejects coercion and unknown fields."""

    model_config = ConfigDict(extra="forbid", strict=True)


class SubmissionInstance(StrictModel):
    """A patch and its explanation for one benchmark instance."""

    instance_id: str
    explanation: str
    model_patch: str | None = None

    @field_validator("instance_id", "explanation")
    @classmethod
    def reject_blank_strings(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a nonempty string")
        return value


class Submission(StrictModel):
    """A complete submission from one model or agent."""

    submission_id: str
    instances: list[SubmissionInstance]

    @field_validator("submission_id")
    @classmethod
    def reject_blank_submission_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a nonempty string")
        return value

    @field_validator("instances")
    @classmethod
    def reject_empty_instances(
        cls, instances: list[SubmissionInstance]
    ) -> list[SubmissionInstance]:
        if not instances:
            raise ValueError("must contain at least one instance")
        return instances

    @model_validator(mode="after")
    def reject_duplicate_instances(self) -> Self:
        seen: set[str] = set()
        duplicates: list[str] = []
        for instance in self.instances:
            if instance.instance_id in seen and instance.instance_id not in duplicates:
                duplicates.append(instance.instance_id)
            seen.add(instance.instance_id)

        if duplicates:
            duplicate_list = ", ".join(repr(item) for item in duplicates)
            raise ValueError(f"duplicate instance_id values: {duplicate_list}")
        return self
