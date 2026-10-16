"""Eval CLI: ``python main.py --data ./dataset/example.json --sandbox local``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from runner import RunConfig, runEval

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def parseDefaultHeaderEntries(
    parser: argparse.ArgumentParser, rawEntries: list[str]
) -> dict[str, str]:
    parsedHeaders: dict[str, str] = {}
    for rawEntry in rawEntries:
        headerKey, separator, headerValue = rawEntry.partition("=")
        cleanedKey = headerKey.strip()
        if not separator or not cleanedKey:
            parser.error(
                "--default-header must look like Key=Value, "
                f"got {rawEntry!r} (repeat the flag for multiple headers)"
            )
        parsedHeaders[cleanedKey] = headerValue.strip()
    return parsedHeaders


def parseCliArgs(argv: list[str] | None = None) -> RunConfig:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Sentinel eval harness (dataset list plus production agent stages)",
    )
    parser.add_argument(
        "--data", default="dataset", help="dataset JSON file or directory of JSON files"
    )
    parser.add_argument(
        "--sandbox", default="local", choices=["local", "docker", "e2b"]
    )
    parser.add_argument("--model", default="openai:gpt-5-mini")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--llm-key", default="")
    parser.add_argument(
        "--default-header",
        action="append",
        default=[],
        help="extra LLM header as Key=Value, repeatable, e.g. --default-header X-G-F=251",
    )
    parser.add_argument("--github-token", default="")
    parser.add_argument("--results-dir", default="results")
    parsedArgs = parser.parse_args(argv)
    baseUrlText = str(parsedArgs.base_url)
    llmKeyText = str(parsedArgs.llm_key)
    if baseUrlText.strip() and not llmKeyText.strip():
        parser.error("--llm-key is required with --base-url")
    return RunConfig(
        datasetPath=str(parsedArgs.data),
        sandbox=parsedArgs.sandbox,
        model=str(parsedArgs.model),
        baseUrl=baseUrlText,
        llmKey=llmKeyText,
        defaultHeaders=parseDefaultHeaderEntries(
            parser, [str(rawEntry) for rawEntry in parsedArgs.default_header]
        ),
        githubToken=str(parsedArgs.github_token),
        resultsDir=str(parsedArgs.results_dir),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        runConfig = parseCliArgs(argv)
    except SystemExit as caughtExit:
        return int(caughtExit.code) if isinstance(caughtExit.code, int) else 2
    try:
        evalResult = asyncio.run(runEval(runConfig))
    except Exception as caughtError:  # noqa: BLE001 -- CLI fails loudly
        print(f"error: {type(caughtError).__name__}: {caughtError}", file=sys.stderr)
        return 1
    from runner import RunError as RunnerError

    if isinstance(evalResult, RunnerError):
        print(f"error [{evalResult.phase}]: {evalResult.message}", file=sys.stderr)
        return 1
    print(f"ok: {evalResult.summary()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
