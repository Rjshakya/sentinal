---
name: fp
description: Use this skill whenever writing, refactoring, or reviewing any pipeline-shaped Python code — a sequence of steps where some steps do I/O (DB, HTTP, filesystem, third-party APIs) and some steps make decisions or transform data. Enforces functional-core/imperative-shell structure: pure functions with explicit inputs/outputs, effects pushed to the edge, Result-based success/error composition instead of exceptions or ad-hoc control flow, enums/Literal types instead of boolean flags, pydantic models at every input/output/serialization boundary, and full static type safety (mypy/pyright strict, no bare Any). Trigger on requests like "refactor this pipeline," "clean up this function," "add a stage to this flow," or any code review where a function mixes business logic with I/O, uses boolean flags for variant state, or passes raw dicts across a boundary.
license: MIT
compatibility: opencode
---

# Functional Core, Imperative Shell — for Python pipelines

Applies to any multi-step Python flow: an ETL job, a request handler, a batch
processor, a CLI command chain — anything with a sequence of steps where some
steps touch the outside world and some steps just transform data.

## The mental model: rings, not layers

Don't think in horizontal layers (controller → service → repo). Think in
concentric **rings**, radiating out from a pure center:

```
        ┌──────────────────────────────────────┐
        │  RING 3 — Shell (impure, at the edge) │
        │  DB sessions, HTTP clients, file I/O,  │
        │  clocks, random, env vars, third-party │
        │  SDKs                                  │
        │   ┌────────────────────────────────┐   │
        │   │ RING 2 — Orchestration          │   │
        │   │ sequences the calls, threads    │   │
        │   │ Result values through, makes    │   │
        │   │ no decisions itself             │   │
        │   │   ┌──────────────────────────┐  │   │
        │   │   │ RING 1 — Core (pure)      │  │   │
        │   │   │ business logic, scoring,  │  │   │
        │   │   │ validation, formatting,   │  │   │
        │   │   │ decisions                 │  │   │
        │   │   └──────────────────────────┘  │   │
        │   └────────────────────────────────┘   │
        └──────────────────────────────────────┘
```

Rule of thumb for where a new function belongs: **imagine its unit test.** If the
test needs a mock, a fixture, a running DB, or a fake clock — it's Ring 3 (or it's
Ring 1 logic leaking into a Ring 3 function). If the test is `assert f(x) == y`
with plain data in and plain data out, it's Ring 1. Most bugs in pipeline code
come from Ring 1 logic getting buried inside a Ring 3 function because "the data
was already right there, easier to just check it inline." Resist that — it's the
single most common way these pipelines rot.

## Rule 1 — Purity in the core

A Ring 1 function:
- Takes every input as an argument. No reading `self.something`, no config
  singletons, no `os.environ` lookups inside the body.
- Returns a value. Never mutates its arguments or a shared object.
- Is deterministic: same inputs → same output, always. No `datetime.now()`,
  `uuid4()`, `random.*` inside the core — generate those in the shell and pass
  them in if the core needs them.
- Raises nothing for *expected* failure paths. Reserve real exceptions for
  programmer errors (bad types, broken invariants). Expected outcomes — validation
  failed, no match, threshold not met — go through `Result` (Rule 3).

```python
# Ring 1 — pure, testable with zero mocks
def apply_discount(order: Order, rules: tuple[DiscountRule, ...]) -> PricedOrder:
    applicable = [r for r in rules if r.matches(order)]
    total = order.subtotal - sum(r.amount(order) for r in applicable)
    return PricedOrder(order=order, applied=applicable, total=max(total, 0))
```

Compare to the anti-pattern this replaces:

```python
# Anti-pattern — pure logic trapped inside an effectful function
async def price_and_save(session: AsyncSession, order_id: str):
    order = await session.get(OrderModel, order_id)          # effect
    rules = await session.execute(select(DiscountRule))       # effect
    applicable = [r for r in rules if r.matches(order)]        # pure logic,
    total = order.subtotal - sum(r.amount(order) for r in applicable)  # buried
    order.total = max(total, 0)                                 # inside an
    await session.commit()                                      # effectful fn
```
The second version can't be unit tested without a real or mocked session, and the
discount math can't be exercised or tweaked in isolation.

## Rule 2 — Effects only at the edge

Ring 3 is the *only* place allowed to:
- open/close a DB session or transaction
- make an HTTP/API call to anything external
- read or write files
- call `time.time()` / `datetime.now()`, generate random values or UUIDs
- read environment variables or config from disk

Everything Ring 3 fetches gets converted into plain data (a dataclass, a tuple, a
primitive — not a lazy ORM row, not a live connection) *before* it's handed
inward. Never pass a live session, client, or connection more than one ring deep.

```python
# Ring 3 — shell. Owns the session and the client, does the I/O.
async def fetch_pricing_inputs(
    session: AsyncSession, order_id: str
) -> Result[tuple[Order, tuple[DiscountRule, ...]], PipelineError]:
    order = await session.get(OrderModel, order_id)             # effect
    if order is None:
        return Err(OrderNotFound(order_id))
    rows = await session.execute(select(DiscountRule))           # effect
    return Ok((Order.from_row(order), tuple(r for r in rows)))    # plain data out
```

### Ports as `Protocol`, not concrete clients

Define each effect's shape as a `Protocol` so Ring 2 code depends on an
interface, not a concrete SDK class. This is what makes the shell swappable (real
implementation in prod, a plain fake in tests) without a mocking framework.

```python
from typing import Protocol

class OrderStore(Protocol):
    async def get(self, order_id: str) -> Order | None: ...
    async def save(self, priced: PricedOrder) -> None: ...

class NotificationSink(Protocol):
    async def send(self, event: PricingEvent) -> Result[None, PipelineError]: ...
```

Test doubles are then just plain classes implementing the `Protocol` — no
`unittest.mock.AsyncMock` needed to test the core or the orchestration.

## Rule 3 — Composability: separate the success and error tracks

Stop using exceptions or `None`-as-failure for expected pipeline outcomes. Use an
explicit `Result[T, E]` and chain stages with `.and_then` / `.map` — "railway
oriented programming": a success value keeps moving down the happy track, an
error short-circuits onto the error track, and nothing downstream needs an
`if error: return` check at every step.

```python
# result.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar, Union

T, U, E, F = TypeVar("T"), TypeVar("U"), TypeVar("E"), TypeVar("F")

@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    value: T
    def and_then(self, fn: Callable[[T], "Result[U, E]"]) -> "Result[U, E]":
        return fn(self.value)
    def map(self, fn: Callable[[T], U]) -> "Result[U, E]":
        return Ok(fn(self.value))
    def map_err(self, fn: Callable[[E], F]) -> "Result[T, F]":
        return self  # type: ignore[return-value]
    def unwrap_or(self, default: T) -> T:
        return self.value
    is_ok = True

@dataclass(frozen=True, slots=True)
class Err(Generic[E]):
    error: E
    def and_then(self, fn: Callable[[T], "Result[U, E]"]) -> "Result[U, E]":
        return self  # type: ignore[return-value]
    def map(self, fn: Callable[[T], U]) -> "Result[U, E]":
        return self  # type: ignore[return-value]
    def map_err(self, fn: Callable[[E], F]) -> "Result[T, F]":
        return Err(fn(self.error))
    def unwrap_or(self, default: T) -> T:
        return default
    is_ok = False

Result = Union[Ok[T], Err[E]]
```

If a third-party dependency is acceptable,
[`returns`](https://github.com/dry-python/returns) provides the same
`Result`/`Success`/`Failure` plus `flow`/`pipe` composition and a `@safe`
decorator for wrapping exception-throwing library calls — prefer it once a
project has more than 2–3 pipeline stages, since it also covers `Future`/IO
containers for async chains. The hand-rolled version above is enough for a
single small pipeline and adds zero dependency weight.

Define error variants as a closed set, not raw strings or a bare `Exception`:

```python
@dataclass(frozen=True, slots=True)
class OrderNotFound:
    order_id: str

@dataclass(frozen=True, slots=True)
class PaymentDeclined:
    reason: str

PipelineError = OrderNotFound | PaymentDeclined
```

### Chaining a pipeline

Ring 2 orchestration becomes a flat chain, each stage returning `Result`:

```python
async def run_checkout(
    store: OrderStore,
    rules: tuple[DiscountRule, ...],
    notify: NotificationSink,
    order_id: str,
) -> Result[PricedOrder, PipelineError]:
    order = await store.get(order_id)
    if order is None:
        return Err(OrderNotFound(order_id))

    return (
        Ok(order)
        .map(lambda o: apply_discount(o, rules))          # Ring 1
        .and_then(validate_total)                          # Ring 1
        .and_then(lambda priced: charge(priced))            # Ring 3 (payment API)
        .and_then(lambda priced: notify_and_return(notify, priced))  # Ring 3
    )
```

No stage needs to check whether an earlier one failed — `Err` just flows through
untouched until something explicitly calls `.and_then` / `.map_err` / `.unwrap_or`
to handle it. The caller at the very top (the route handler, the CLI entrypoint,
the queue consumer) is the only place that converts a final `Err` into a response,
a log line, or a retry decision.

## Rule 4 — Enums / `Literal` instead of boolean flags

A pile of boolean flags is a hidden enum that never got named — and it lets
invalid states exist (`is_openai=True, is_anthropic=True` compiles fine, means
nothing). Every time a value can be "one of N known things," name that set
explicitly and let the type checker rule out the impossible combinations.

```python
# Anti-pattern — flags that can contradict each other, and a 3rd provider
# means touching every call site that checks these
def call_llm(prompt: str, is_openai: bool = False, is_anthropic: bool = False): ...

# Preferred — one axis of variation, exhaustively checkable
class Provider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"

def call_llm(prompt: str, provider: Provider) -> Result[str, LLMError]:
    match provider:
        case Provider.OPENAI: ...
        case Provider.ANTHROPIC: ...
        case Provider.GOOGLE: ...
        # no `case _` needed — pyright/mypy flags a missing branch if a
        # provider is added and this match isn't updated
```

`StrEnum` (3.11+) over plain `Enum` when the value needs to serialize cleanly
(JSON bodies, DB columns, CLI args) — you get `Provider.OPENAI == "openai"` for
free instead of writing a custom `__str__`/encoder. Use `Literal["openai",
"anthropic", "google"]` instead of a full `Enum` class for a one-off type
annotation that doesn't need methods or iteration — both give exhaustiveness
checking, `Enum` is worth it once the variants show up in more than one
signature or need attached data (e.g. `.default_model` per provider).

The same applies beyond providers: status flags (`is_pending`/`is_done`/
`is_failed` → `Status` enum), modes, environments, anything with a fixed,
enumerable set of states. If you catch yourself adding a second boolean that's
only meaningful in combination with the first, that's the signal to collapse
both into one enum.

## Rule 5 — Pydantic models at every boundary

Anywhere data crosses a trust or process boundary — an API request/response, a
DB row headed out of Ring 3, a config file, a queue message, anything
`.json()`'d or `.dict()`'d — define it as a `pydantic.BaseModel`, not a bare
`dict[str, Any]` or an unvalidated dataclass. This gets you three things at
once: input validation (reject garbage before it reaches the core), consistent
serialization/deserialization, and a schema the rest of the team (or an OpenAPI
doc) can read.

```python
class Order(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    id: str
    subtotal: Decimal
    provider: Provider
    items: tuple[OrderItem, ...]

class PricedOrder(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    order: Order
    applied_discounts: tuple[DiscountRule, ...]
    total: Decimal

    @field_validator("total")
    @classmethod
    def total_not_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("total cannot be negative")
        return v
```

Rules of thumb for where to reach for `BaseModel` vs. a plain `dataclass`:

- **External or untrusted data → always `BaseModel`.** API payloads, third-party
  responses, file/config contents, anything from a queue. Parse it once at the
  Ring 3 boundary with `Order.model_validate(raw_json)` (or `TypeAdapter` for
  lists/unions) and hand a validated model inward — never pass a raw `dict`
  past the function that received it.
  ```python
  orders = TypeAdapter(list[Order]).validate_python(raw_rows)
  ```
- **Values returned from the API layer → always `BaseModel`.** `model_dump_json()`
  / FastAPI's response_model handling give you serialization for free and keep
  the response shape in sync with the type.
  ```python
  return priced.model_dump(mode="json")
  ```
- **Purely internal Ring 1 intermediates that never leave the process and never
  came from outside → a frozen `dataclass`/`NamedTuple` is fine**, since the
  data was already validated once on the way in and re-validating on every
  internal function call is wasted work in a hot pure-computation path. Don't
  feel obligated to wrap every intermediate tuple in a `BaseModel` — the rule
  is about boundaries, not about replacing every type in the codebase.
- Set `model_config = ConfigDict(frozen=True)` on models that flow through Ring
  1/2 so they behave like the immutable values Rule 1 expects — a mutable
  pydantic model passed into "pure" functions reintroduces the exact hazard
  purity is meant to remove.

## Rule 6 — Full type safety, no exceptions for "just this once"

Treat the type checker as a build step, not a suggestion:

- Run `mypy --strict` or `pyright` in strict mode in CI. Both are fine; pick one
  and enforce it — a codebase that's "mostly typed" gives none of the guarantees
  this skill relies on, because the untyped 10% is exactly where bugs hide.
- No bare `Any`. If a value's shape is genuinely unknown until runtime (e.g. a
  third-party SDK with poor stubs), narrow it immediately with a `BaseModel`
  (Rule 5) or a `TypeGuard`, don't let `Any` propagate past the function that
  received it.
- No `# type: ignore` without a reason comment (`# type: ignore[arg-type]  #
  <why>`) — an unexplained ignore is a future bug waiting to be re-discovered.
- Every `Protocol` (ports, Rule 2), every `Result[T, E]` (Rule 3), every enum
  (Rule 4), and every `BaseModel` (Rule 5) should have its type parameters
  filled in concretely at the call site — `Result[PricedOrder, PipelineError]`,
  not `Result` on its own with implicit `Any`s.
- Prefer `match`/`case` over `if`/`elif` chains on an enum or a `Result` —
  strict type checkers can flag a missing case; an `if/elif` chain can't tell
  you a branch is missing.
- Function signatures are the contract: every Ring 1 and Ring 2 function should
  have a fully typed signature with no default `Any`, including generics
  (`list[Order]`, not `list`). A pure function with a strict, narrow signature
  is close to self-documenting and close to un-misusable at the call site.

## Applying this to an existing function

When refactoring a pipeline-shaped function, work in this order:

1. **List every effect.** DB calls, network calls, file reads, clock/random
   reads. These mark the Ring 3 boundary.
2. **Extract the decisions.** Anything that's a computation over already-fetched
   data (filtering, scoring, formatting, validating) becomes a Ring 1 function
   with a plain dataclass/primitive in, plain dataclass/primitive out.
3. **Replace exceptions/`None` for expected failures with `Result`.** Keep real
   exceptions only for things that indicate a bug, not a business outcome.
4. **Write the Ring 2 orchestration as a chain**, not a sequence of
   `if`/`await`/inline-error-handling.
5. **Sanity check the core.** If a "pure" function still needs `async def`, a
   session, or a fixture to test — it hasn't actually been extracted yet. Push
   the remaining effect one ring further out.

## Review checklist

- [ ] Does any function mix an I/O call with `if`/scoring/validation logic in the
      same body? → split it.
- [ ] Are expected failure conditions (not-found, validation, rate limit) handled
      with bare `try/except` instead of a `Result` return? → convert.
- [ ] Does a "pure-looking" function call `datetime.now()`, `uuid4()`, or read
      global config/env vars? → inject as an argument instead.
- [ ] Is a live session/client/connection passed more than one ring deep? → stop
      at Ring 3; convert to plain data before passing inward.
- [ ] Can each Ring 1 function be tested with a plain `assert f(x) == y` — no
      `AsyncMock`, no DB fixture? If not, it's misplaced.
- [ ] Are pipeline error variants an explicit closed union (dataclasses / `Enum`),
      not raw strings or bare `Exception`?
- [ ] Is there more than one boolean flag describing "which kind of X is this"?
      → collapse into an `Enum`/`Literal`.
- [ ] Does anything crossing a boundary (API in/out, DB row, config, queue
      message) arrive or leave as a raw `dict`/`Any` instead of a `BaseModel`?
      → wrap it.
- [ ] Does `mypy --strict`/`pyright --strict` pass with no new `Any` or
      unexplained `# type: ignore`?

## Anti-patterns to flag

- **God orchestrator**: one big `async def process(...)` that both fetches and
  decides. Fine as a first draft, not fine to merge — split per Rule 1/2.
- **Silent `None`**: `def find(...) -> Thing | None` used as ersatz error
  handling. Prefer `Result[Thing, NotFoundError]` — `None` doesn't say *why*.
- **Effect leakage**: passing `session`/`client`/`connection` into a function whose
  name implies pure logic (`score`, `format`, `is_valid`). If it takes a live
  handle, it's Ring 3 by definition — rename it or refactor it.
- **Partial railway**: chaining `.map()` calls but then wrapping the whole thing
  in `try/except Exception` at the call site anyway. Pick one error-handling
  model per pipeline and stay consistent.
- **Boolean flag soup**: two or more `is_*`/`has_*` params on one function that
  are only meaningful together. Collapse into one `Enum`/`Literal` (Rule 4).
- **`dict`/`Any` at the boundary**: parsing a request body, DB row, or config
  file into a raw `dict` and passing it inward unvalidated. Parse into a
  `BaseModel` once, at the edge (Rule 5), and pass the validated model inward.
