"""DBOS durable workflows, built on the refactored service layer.

Each workflow package owns one domain pipeline and follows the new
service conventions:

- ``types.py``  — the contract: serializable ctxs, workflow inputs,
  result projections. Ids are branded types from
  :mod:`app.utils.branded`.
- ``errors.py`` — error values (BaseModel) returned by pure step
  functions, plus the raised step-exception wrappers used by the DBOS
  step edges.
- ``workflow.py`` — the DBOS orchestrator plus its pure helpers.
- ``steps/``    — one file per I/O boundary: a pure function (returns
  ``T | ErrorValue``, no logging, no DBOS, no raising) and a DBOS
  edge (logs and raises for retries / business outcomes).
"""

from __future__ import annotations