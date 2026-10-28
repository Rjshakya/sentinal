"""Error values for pi session cost reads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PiCostError(BaseModel):
    """A session cost that could not be read (missing file, bad parse)."""

    model_config = ConfigDict(frozen=True)

    message: str


__all__ = ["PiCostError"]
