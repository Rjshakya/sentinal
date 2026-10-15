"""Dataset contract: PR inputs, gold outputs, and their pairing.

``Dataset`` holds two parallel lists: ``inputs[i]`` is the PR under
review and ``outputs[i]`` is the expected result for that PR. The
index pairing is the whole contract -- never reorder one list without
the other.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GoldSeverity = Literal["P1_CRITICAL", "P2_WARNING", "P3_NITPICK"]
GoldVerdict = Literal["APPROVE", "COMMENT", "REQUEST_CHANGES"]


class PrInput(BaseModel):
    """PR facts for one eval case. No secrets, no infra, no DB ids."""

    model_config = ConfigDict(frozen=True)

    repo_url: str = Field(min_length=1, max_length=1024)
    owner: str = Field(min_length=1)
    name: str = Field(min_length=1)
    pr_number: int = Field(ge=1)
    base_sha: str = Field(min_length=7, max_length=64)
    head_sha: str = Field(min_length=7, max_length=64)
    base_branch: str = Field(default="main", min_length=1)
    head_branch: str = Field(default="", min_length=0)
    title: str = Field(default="")
    author: str = Field(default="")
    body: str = Field(default="")


class GoldBug(BaseModel):
    """One ground-truth finding the reviewer is expected to report."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    bug: str = Field(min_length=1)
    location: str = Field(min_length=1)
    severity: GoldSeverity


class GoldOutput(BaseModel):
    """Expected review result for one PR."""

    model_config = ConfigDict(frozen=True)

    verdict: GoldVerdict
    bugs: Annotated[list[GoldBug], Field(default_factory=list)]


class Dataset(BaseModel):
    """Parallel inputs/outputs. ``inputs[i]`` maps to ``outputs[i]``."""

    model_config = ConfigDict(frozen=True)

    inputs: list[PrInput]
    outputs: list[GoldOutput]
    ids: Annotated[list[str], Field(default_factory=list)]

    @model_validator(mode="after")
    def _check_pairing(self) -> Dataset:
        if len(self.inputs) != len(self.outputs):
            raise ValueError(
                f"inputs ({len(self.inputs)}) and outputs ({len(self.outputs)}) "
                "must have equal length"
            )
        if self.ids and len(self.ids) != len(self.inputs):
            raise ValueError(
                f"ids ({len(self.ids)}) must match inputs ({len(self.inputs)})"
            )
        return self

    def __len__(self) -> int:
        return len(self.inputs)


__all__ = [
    "Dataset",
    "GoldBug",
    "GoldOutput",
    "GoldSeverity",
    "GoldVerdict",
    "PrInput",
]
