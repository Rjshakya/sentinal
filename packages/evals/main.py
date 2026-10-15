"""Eval CLI: ``python main.py --data ./dataset --env local``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from runner import RunConfig, runEval

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _parse_args(argv: list[str] | None = None) -> RunConfig:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Sentinel eval harness (dataset + production agent stages)",
    )
    parser.add_argument("--data", default="dataset", help="dataset root folder")
    parser.add_argument("--env", default="local", choices=["local", "docker", "e2b"])
    parser.add_argument("--model", default="openai:gpt-5-mini")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--out", default="report")
    args = parser.parse_args(argv)
    return RunConfig(
        dataset_path=str(args.data),
        env=args.env,  # type: ignore[arg-type]
        model=str(args.model),
        base_url=str(args.base_url),
        api_key=str(args.api_key),
        out_dir=str(args.out),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        cfg = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    try:
        result = asyncio.run(runEval(cfg))
    except Exception as exc:  # noqa: BLE001 -- CLI fails loudly
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    from runner import RunError as _RunError

    if isinstance(result, _RunError):
        print(f"error [{result.phase}]: {result.message}", file=sys.stderr)
        return 1
    print(f"ok: {result.summary()} -> {cfg.out_dir}/report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
