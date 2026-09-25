from pathlib import Path

import yaml
from pydantic import BaseModel

from agentqa.contracts.verify import AssertionSpec


class TestCase(BaseModel):
    name: str
    start_path: str
    goal: str
    max_steps: int = 20
    assertions: list[AssertionSpec] = []


def load_case(path: Path) -> TestCase:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"case file must contain a mapping: {path}")
    return TestCase.model_validate(raw)
