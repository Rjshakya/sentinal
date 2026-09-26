"""Build the pre-baked E2B sandbox template for agent sandboxes.

Base is the stock ``code-interpreter-v1`` image plus the pinned
``sentinel-codegraph`` CLI (see
:mod:`app.services.sandbox.e2b_template`). Every build overwrites the
same template name, so ``E2B_TEMPLATE`` keeps resolving with no config
change. Runs locally and in CI
(``.github/workflows/build-template.yml``); exits nonzero on failure
so CI gates on it.

Run from ``packages/api/``:

    uv run python scripts/build_e2b_template.py
"""

from __future__ import annotations

import logging
import sys

from app.services.sandbox.e2b_template import build_e2b_template

log = logging.getLogger(__name__)


def main() -> int:
    log.info("building e2b template…")
    build_info = build_e2b_template()
    log.info("template built: %s", build_info)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
