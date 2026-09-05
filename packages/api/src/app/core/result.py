"""Hand-rolled ``Result`` type for the setup pipeline.

This module intentionally re-implements ``Ok`` / ``Err`` / ``Result``
instead of depending on a third-party library (e.g. ``returns``). The
setup pipeline is the only consumer in this codebase, and a small
in-tree implementation keeps the dependency surface flat.

Two design rules, both followed by every caller:

1. Pure functions (Ring 1) return ``Result[...]`` for *expected*
   failure paths and reserve real exceptions for programmer errors
   (bad input types, broken invariants). The pipeline orchestrator
   never raises for expected outcomes.

2. The single outermost ``try / except`` in the orchestrator catches
   anything that escapes the typed pipeline. This module defines no
   ``try / except`` itself.

The success type ``T`` and error type ``E`` are *covariant* so that
the standard subtyping rules apply — ``Ok[Cat]`` is a subtype of
``Ok[Animal]`` and ``Err[NotFound]`` is a subtype of
``Err[NotFound | ServerError]``. This lets the orchestrator widen
a narrow ``Err`` from a Ring-1 helper to a union error type at the
pipeline boundary without an explicit ``cast``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

T = TypeVar("T", covariant=True)
U = TypeVar("U")
E_co = TypeVar("E_co", covariant=True)
F = TypeVar("F")
T_default = TypeVar("T_default")


@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    """Success variant of :class:`Result`."""

    value: T

    @property
    def is_ok(self) -> Literal[True]:
        return True

    @property
    def is_err(self) -> Literal[False]:
        return False

    def and_then(self, fn: Callable[[T], Result[U, E_co]]) -> Result[U, E_co]:
        return fn(self.value)

    def map(self, fn: Callable[[T], U]) -> Result[U, E_co]:
        return Ok(fn(self.value))

    def map_err(self, fn: Callable[[E_co], F]) -> Result[T, F]:
        return self

    def unwrap_or(self, default: T_default) -> T | T_default:
        return self.value

    def unwrap_or_else(self, fn: Callable[[E_co], T_default]) -> T | T_default:
        return self.value


@dataclass(frozen=True, slots=True)
class Err(Generic[E_co]):
    """Failure variant of :class:`Result`."""

    error: E_co

    @property
    def is_ok(self) -> Literal[False]:
        return False

    @property
    def is_err(self) -> Literal[True]:
        return True

    def and_then(self, fn: Callable[[T], Result[U, E_co]]) -> Result[U, E_co]:
        return self

    def map(self, fn: Callable[[T], U]) -> Result[U, E_co]:
        return self

    def map_err(self, fn: Callable[[E_co], F]) -> Result[T, F]:
        return Err(fn(self.error))

    def unwrap_or(self, default: T_default) -> T_default:
        return default

    def unwrap_or_else(self, fn: Callable[[E_co], T_default]) -> T_default:
        return fn(self.error)


Result = Ok[T] | Err[E_co]
"""A value of type ``T`` on success, or an error of type ``E`` on failure."""


__all__ = ["Err", "Ok", "Result"]
