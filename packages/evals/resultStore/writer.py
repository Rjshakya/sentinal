"""Result store writer: model dir plus evaluations file.

Directory rule: take the part after the first ``:`` in the RunConfig
model string (``openai:gpt-5-mini`` becomes ``gpt-5-mini``), slugify it
for the filesystem, and write ``evaluations.json`` inside
``results/{modelId}/``. All paths use :class:`pathlib.Path`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from metrics.scoring import DatasetMetrics
from resultStore.types import EvaluationsFile, PrEvaluation, ResultStoreError


def buildModelDirName(model: str) -> str:
    cleanedModel = model.strip()
    tailPart = cleanedModel.split(":", 1)[1] if ":" in cleanedModel else cleanedModel
    slugChars: list[str] = []
    for rawChar in tailPart.strip().lower():
        if rawChar.isalnum() or rawChar in ("-", "_", "."):
            slugChars.append(rawChar)
        else:
            slugChars.append("-")
    slugName = "".join(slugChars).strip("-_.")
    if not slugName:
        return "unknown-model"
    return slugName


def buildEvaluationsFilePath(resultsDir: Path, model: str) -> Path:
    return resultsDir / buildModelDirName(model) / "evaluations.json"


def buildEvaluationsFile(
    datasetPath: str,
    env: str,
    datasetMetrics: DatasetMetrics,
    evaluations: list[PrEvaluation],
) -> EvaluationsFile:
    createdAt = datetime.now(timezone.utc).isoformat()
    return EvaluationsFile(
        createdAt=createdAt,
        datasetPath=datasetPath,
        env=env,
        datasetMetrics=datasetMetrics,
        evaluations=list(evaluations),
    )


def saveEvaluationsFile(filePath: Path, evaluationsFile: EvaluationsFile) -> None | ResultStoreError:
    try:
        parentDir = filePath.parent
        parentDir.mkdir(parents=True, exist_ok=True)
        filePath.write_text(evaluationsFile.model_dump_json(indent=2), encoding="utf-8")
        return None
    except OSError as caughtError:
        return ResultStoreError(
            message=f"cannot write evaluations file {filePath}: {type(caughtError).__name__}: {caughtError}",
            path=str(filePath),
        )


__all__ = [
    "buildEvaluationsFile",
    "buildEvaluationsFilePath",
    "buildModelDirName",
    "saveEvaluationsFile",
]
