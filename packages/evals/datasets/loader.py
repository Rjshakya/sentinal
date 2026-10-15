"""Dataset loader: folders of ``input.json`` / ``output.json`` pairs."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from datasets.types import Dataset, GoldOutput, PrInput


class DatasetError(BaseModel):
    """Loader failure, returned as a value (never raised)."""

    model_config = ConfigDict(frozen=True)

    message: str
    path: str | None = None

    def __str__(self) -> str:
        return self.message


def _read_json(path: Path) -> dict[str, object] | DatasetError:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DatasetError(message=f"missing file: {path}", path=str(path))
    except json.JSONDecodeError as exc:
        return DatasetError(
            message=f"invalid JSON in {path}: {exc}", path=str(path)
        )
    if not isinstance(raw, dict):
        return DatasetError(
            message=f"expected a JSON object in {path}", path=str(path)
        )
    return raw


def loadDataset(root: str | Path) -> Dataset | DatasetError:
    """Load every ``<root>/<case>/{input,output}.json`` pair, sorted by name.

    Each immediate subdirectory of ``root`` is one case: ``input.json``
    validates into :class:`PrInput`, ``output.json` into
    :class:`GoldOutput`. Returns a :class:`DatasetError` value when the
    root is missing, a case is malformed, or validation fails.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        return DatasetError(
            message=f"dataset root is not a directory: {root_path}",
            path=str(root_path),
        )

    case_dirs = sorted(p for p in root_path.iterdir() if p.is_dir())
    if not case_dirs:
        return DatasetError(
            message=f"dataset root has no case folders: {root_path}",
            path=str(root_path),
        )

    inputs: list[PrInput] = []
    outputs: list[GoldOutput] = []
    ids: list[str] = []
    for case_dir in case_dirs:
        input_raw = _read_json(case_dir / "input.json")
        if isinstance(input_raw, DatasetError):
            return input_raw
        output_raw = _read_json(case_dir / "output.json")
        if isinstance(output_raw, DatasetError):
            return output_raw
        try:
            pr_input = PrInput.model_validate(input_raw)
        except Exception as exc:
            return DatasetError(
                message=f"invalid input.json in {case_dir.name}: {exc}",
                path=str(case_dir / "input.json"),
            )
        try:
            gold = GoldOutput.model_validate(output_raw)
        except Exception as exc:
            return DatasetError(
                message=f"invalid output.json in {case_dir.name}: {exc}",
                path=str(case_dir / "output.json"),
            )
        inputs.append(pr_input)
        outputs.append(gold)
        ids.append(case_dir.name)

    try:
        return Dataset(inputs=inputs, outputs=outputs, ids=ids)
    except Exception as exc:
        return DatasetError(message=f"invalid dataset pairing: {exc}")


__all__ = ["DatasetError", "loadDataset"]
