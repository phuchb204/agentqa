from __future__ import annotations

from typing import Literal

from pydantic import Field

from agentqa.contracts.case import RequirementContent
from agentqa.contracts.values import StrictModel


class EnvironmentRevisionContent(StrictModel):
    schema_version: Literal["environment/1"]
    base_url: str
    network_profile: str
    auth_profile: str | None = None
    fixture_refs: list[str] = Field(default_factory=list)
    role_binding: dict[str, str] = Field(default_factory=dict)
    allowed_origins: list[str] = Field(default_factory=list)
    allow_write_actions: bool = False


class SuiteCaseRef(StrictModel):
    logical_key: str
    revision_no: int


class SuiteRevisionContent(StrictModel):
    schema_version: Literal["suite/1"]
    logical_key: str
    case_refs: list[SuiteCaseRef]
    dataset_ref: str | None = None
    fixture_refs: list[str] = Field(default_factory=list)
    execution_mode: Literal["serial", "parallel"] = "serial"


class DatasetRevisionContent(StrictModel):
    schema_version: Literal["dataset/1"]
    logical_key: str
    privacy_class: Literal["synthetic", "internal", "pii"] = "synthetic"
    rows: list[dict] = Field(default_factory=list)


class FixtureRevisionContent(StrictModel):
    schema_version: Literal["fixture/1"]
    logical_key: str
    capabilities: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)


CONTENT_MODELS = {
    "environment": EnvironmentRevisionContent,
    "requirement": RequirementContent,
    "suite": SuiteRevisionContent,
    "dataset": DatasetRevisionContent,
    "fixture": FixtureRevisionContent,
}
