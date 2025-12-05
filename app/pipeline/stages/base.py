"""Base building blocks for pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol


Context = Dict[str, Any]


class Stage(Protocol):
    name: str
    queue: str

    def run(self, context: Context) -> Context:
        ...


@dataclass
class StageResult:
    name: str
    context: Context
    metrics: Dict[str, Any]


def apply_stage(stage: Stage, context: Context) -> StageResult:
    metrics: Dict[str, Any] = {}
    result = stage.run(context)
    return StageResult(name=stage.name, context=result, metrics=metrics)
