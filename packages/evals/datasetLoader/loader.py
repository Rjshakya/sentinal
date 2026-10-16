"""Dataset list loader: JSON file or directory of JSON files.

Accepted shape per file is either a JSON list of DatasetEntry rows or a
single DatasetEntry object. A directory root loads every top-level
``*.json`` file (sorted by name) and concatenates the rows in order.
"""

from __future__ import annotations

import json
from pathlib import Path

from datasetLoader.types import DatasetEntry, DatasetLoaderError
from pydantic import BaseModel, ConfigDict


class LoadedDataset(BaseModel):
    """Loaded dataset rows in stable order."""

    model_config = ConfigDict(frozen=True)

    entries: list[DatasetEntry]
    sources: list[str]


def readJsonDocument(filePath: Path) -> object | DatasetLoaderError:
    try:
        rawText = filePath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DatasetLoaderError(message=f"missing file: {filePath}", path=str(filePath))
    except OSError as caughtError:
        return DatasetLoaderError(
            message=f"cannot read file {filePath}: {type(caughtError).__name__}: {caughtError}",
            path=str(filePath),
        )
    try:
        return json.loads(rawText)
    except json.JSONDecodeError as caughtError:
        return DatasetLoaderError(
            message=f"invalid JSON in {filePath}: {caughtError}",
            path=str(filePath),
        )


def parseEntryObject(rawEntry: object, sourceLabel: str) -> DatasetEntry | DatasetLoaderError:
    if not isinstance(rawEntry, dict):
        return DatasetLoaderError(
            message=f"expected a JSON object for dataset entry in {sourceLabel}",
            path=sourceLabel,
        )
    try:
        return DatasetEntry.model_validate(rawEntry)
    except Exception as caughtError:
        return DatasetLoaderError(
            message=f"invalid dataset entry in {sourceLabel}: {caughtError}",
            path=sourceLabel,
        )


def parseEntryDocument(rawDocument: object, sourceLabel: str) -> list[DatasetEntry] | DatasetLoaderError:
    if isinstance(rawDocument, dict):
        singleEntry = parseEntryObject(rawDocument, sourceLabel)
        if isinstance(singleEntry, DatasetLoaderError):
            return singleEntry
        return [singleEntry]
    if isinstance(rawDocument, list):
        parsedEntries: list[DatasetEntry] = []
        for index, rawEntry in enumerate(rawDocument):
            parsedEntry = parseEntryObject(rawEntry, f"{sourceLabel}[{index}]")
            if isinstance(parsedEntry, DatasetLoaderError):
                return parsedEntry
            parsedEntries.append(parsedEntry)
        return parsedEntries
    return DatasetLoaderError(
        message=f"expected a JSON object or list in {sourceLabel}",
        path=sourceLabel,
    )


def collectJsonFiles(datasetDir: Path) -> list[Path]:
    return sorted(path for path in datasetDir.iterdir() if path.is_file() and path.suffix == ".json")


def loadFileEntries(jsonFile: Path) -> list[DatasetEntry] | DatasetLoaderError:
    rawDocument = readJsonDocument(jsonFile)
    if isinstance(rawDocument, DatasetLoaderError):
        return rawDocument
    return parseEntryDocument(rawDocument, str(jsonFile))


def loadDatasetEntries(datasetPath: str | Path) -> LoadedDataset | DatasetLoaderError:
    """Load dataset entries from a JSON file or a directory of JSON files."""
    rootPath = Path(datasetPath)
    if rootPath.is_file():
        fileEntries = loadFileEntries(rootPath)
        if isinstance(fileEntries, DatasetLoaderError):
            return fileEntries
        if not fileEntries:
            return DatasetLoaderError(
                message=f"dataset file has no entries: {rootPath}",
                path=str(rootPath),
            )
        return LoadedDataset(entries=fileEntries, sources=[str(rootPath)])
    if rootPath.is_dir():
        jsonFiles = collectJsonFiles(rootPath)
        if not jsonFiles:
            return DatasetLoaderError(
                message=f"dataset directory has no JSON files: {rootPath}",
                path=str(rootPath),
            )
        mergedEntries: list[DatasetEntry] = []
        mergedSources: list[str] = []
        for jsonFile in jsonFiles:
            fileEntries = loadFileEntries(jsonFile)
            if isinstance(fileEntries, DatasetLoaderError):
                return fileEntries
            mergedEntries.extend(fileEntries)
            mergedSources.append(str(jsonFile))
        if not mergedEntries:
            return DatasetLoaderError(
                message=f"dataset directory has no entries: {rootPath}",
                path=str(rootPath),
            )
        return LoadedDataset(entries=mergedEntries, sources=mergedSources)
    return DatasetLoaderError(
        message=f"dataset path is not a file or directory: {rootPath}",
        path=str(rootPath),
    )


__all__ = ["LoadedDataset", "loadDatasetEntries"]
