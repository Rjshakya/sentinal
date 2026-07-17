"""Review pipeline — pure functional, three rings.

Layout:

- **Ring 1 (pure)**      — prompt assembly, draft→row mapping, error
  flattening, chat-model factory. No I/O, no session, no clock.
- **Ring 2 (orchestrator)** — :func:`run` sequences I/O and threads
  ``Result`` values through the pipeline. Single outermost
  ``try / except`` catches anything that escapes the typed pipeline
  and folds it into ``Err(ReviewAgentCrashed)``.
- **Ring 3 (shell / I/O)** — :func:`get_repo_record`, :func:`get_sandbox`,
  :func:`get_diff`, :func:`_upsert_pull_request`, :func:`_persist_review_summary`,
  :func:`_persist_code_comments`. Each is the single boundary into an
  external system (DB, E2B, LLM SDK) and is the only place that catches
  the underlying SDK's exceptions.

No ``class`` is defined in this module — every abstraction is a
function. The only ``class`` keywords in the import surface are
external: SQLModel tables, the ``Repository`` wrapper, the E2B client,
and the chat model. The pipeline itself is values in, values out.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeAlias

from deepagents import SubAgent, create_deep_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_e2b import AsyncE2BSandbox
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.github_app import installation_client
from app.core.result import Err, Ok, Result
from app.core.sandbox import BaseSandbox
from app.core.sandbox.e2b import E2BSandbox, E2BSandboxSpec
from app.models.code_comment import CodeComment
from app.models.enums import (
    CommentSeverity,
    CommentSide,
    CommentState,
    PRStatus,
    ReviewVerdict,
)
from app.models.pull_request import PullRequest
from app.models.repo import Repo as RepoModel
from app.models.review_summary import ReviewSummary
from app.models.sandbox import Sandbox as SandboxModel
from app.repositories import Repository
from app.services.agent.models import CodeCommentDraft, ReviewResult
from app.services.agent.prompts import (
    CORRECTNESS_SYSTEM_PROMPT,
    PR_SUMMARY_SYSTEM_PROMPT,
    REVIEW_ORCHESTRATOR_SYSTEM_PROMPT,
    SECURITY_SYSTEM_PROMPT,
    STYLE_SYSTEM_PROMPT,
)
from app.services.github.post_review import (
    GitHubAuthFailed,
    GitHubCommentPostFailed,
    GitHubPRNotFound,
    GitHubRateLimited,
    GitHubReviewPostFailed,
    post_review_and_update_db,
)
from app.services.review.errors import (
    DiffUnavailable,
    NoActiveSandbox,
    RepoNotFound,
    ReviewAgentCrashed,
    ReviewAgentReturnedNoStructuredResponse,
    ReviewPipelineError,
    SandboxConnectFailed,
)
from app.services.review.types import ReviewRunResult
from app.utils.util import repo_path, uuidToStr

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# types                                                                       #
# --------------------------------------------------------------------------- #


LLMProviderStr: TypeAlias = Literal["openai", "anthropic", "google"]
"""Allowed values for :attr:`Input.provider`. Validated at chat-model
construction time by :func:`build_chat_model`."""


DeepAgentGraph: TypeAlias = CompiledStateGraph
"""The compiled langgraph state graph returned by ``create_deep_agent``.

The alias is module-level so callers can name the return type of
:func:`get_review_agent` without pulling langgraph types into their own
signatures."""


@dataclass(frozen=True, slots=True)
class Input:
    """Everything :func:`run` needs to review one PR.

    ``branch`` is the *base* branch (i.e. the branch the PR is merging
    into). The head ref is intentionally not modelled here — the only
    head information the review needs is the commit SHA, which is
    ``head_sha``.
    """

    session: AsyncSession
    user_id: str
    gh_repo_id: int
    pr_id: int
    pr_number: int
    branch: str
    base_sha: str
    head_sha: str
    head_branch: str
    author: str
    body: str
    title: str
    status: PRStatus
    llm_baseurl: str | None
    llm_api_key: str
    llm_model: str
    provider: LLMProviderStr
    spec: E2BSandboxSpec
    # GitHub posting fields
    github_installation_id: int | None = None
    post_to_github: bool = False


DiffProviderFn: TypeAlias = Callable[..., Awaitable[Result[str, DiffUnavailable]]]
"""Type alias for the diff-source port. Concrete implementations are
plain functions or closures; no class is required."""


ReviewAgentRunnerFn: TypeAlias = Callable[
    ...,
    Awaitable[
        Result[
            ReviewResult,
            ReviewAgentCrashed | ReviewAgentReturnedNoStructuredResponse,
        ]
    ],
]
"""Type alias for the LLM-SDK boundary. The orchestrator calls this
once per review; implementations are responsible for catching the
underlying SDK's exceptions and turning them into the typed ``Err``
variants."""


# --------------------------------------------------------------------------- #
# Ring 1 — pure helpers                                                       #
# --------------------------------------------------------------------------- #


def assemble_orchestrator_system_prompt() -> str:
    """Return the system prompt for the orchestrator deep-agent.

    The orchestrator is the single ``create_deep_agent`` instance; the
    three specialists (security / correctness / style) are wired in
    as :class:`SubAgent` children via :func:`assemble_review_subagents`.
    Pure: no I/O, no clock.
    """
    return REVIEW_ORCHESTRATOR_SYSTEM_PROMPT


def assemble_review_subagents() -> list[SubAgent]:
    """Return the four specialist subagents the orchestrator delegates to.

    Each subagent gets a unique ``name`` (used as the dispatch key in
    the orchestrator's ``task()`` tool), a one-line ``description`` the
    orchestrator uses to decide which subagent to call, and the
    specialist's own system prompt. Tools are intentionally not set:
    the deepagents runtime inherits the parent's backend tools (the
    E2B sandbox's ``read`` / ``write`` / ``execute`` / etc.), so each
    specialist can verify a suspicion against the repo when needed.
    Pure: no I/O, no clock.

    The first subagent, ``summarizer``, is the PR-summary writer. The
    orchestrator calls it first, takes its markdown output verbatim,
    and embeds it as ``ReviewResult.summary`` (which is then persisted
    as the PR's review summary). The other three are the existing
    severity-bucketed reviewers and only emit findings, not prose.
    """
    return [
        SubAgent(
            name="summarizer",
            description=(
                "PR summary writer. Emits a grounded markdown bullet "
                "list of what the PR does (one-line title + bullets "
                "with file:line references). Call this FIRST; its "
                "output is embedded verbatim as ReviewResult.summary "
                "and persisted as the PR's review summary. Does not "
                "emit findings, bugs, or verdicts."
            ),
            system_prompt=PR_SUMMARY_SYSTEM_PROMPT,
        ),
        SubAgent(
            name="security",
            description=(
                "Security reviewer. Emits only P1_CRITICAL findings. "
                "Delegate to it whenever the orchestrator suspects an "
                "injection, secrets leak, auth bypass, or other "
                "security-class bug."
            ),
            system_prompt=SECURITY_SYSTEM_PROMPT,
        ),
        SubAgent(
            name="correctness",
            description=(
                "Correctness reviewer. Emits only P2_WARNING findings. "
                "Delegate to it for off-by-one, missing error handling, "
                "race conditions, API misuse, and similar logic bugs."
            ),
            system_prompt=CORRECTNESS_SYSTEM_PROMPT,
        ),
        SubAgent(
            name="style",
            description=(
                "Style reviewer. Emits only P3_NITPICK findings. "
                "Delegate to it for misleading names, dead code, "
                "stale comments, and other lintable cleanups."
            ),
            system_prompt=STYLE_SYSTEM_PROMPT,
        ),
    ]


def assemble_user_prompt(
    *,
    repo_name: str,
    repo_id: str,
    user_id: str,
    pr_number: int,
    diff: str,
) -> str:
    """Build the user message sent to the review deep-agent.

    Pure formatting — no I/O, no LLM. Mirrors the structure of
    :func:`app.services.agent.setup.assemble_setup_user_prompt` so
    the setup and review agents have a consistent prompt shape.
    """
    return (
        f"Repo: {repo_name} (id={repo_id})\n"
        f"User: {user_id}\n"
        f"PR number: {pr_number}\n"
        f"\n"
        f"--- DIFF ---\n"
        f"{diff}\n"
        f"--- END DIFF ---\n"
    )


def get_repo_path(repo_name: str) -> str:
    """Return the in-sandbox path of the cloned ``repo_name``.

    Pure wrapper over :func:`app.utils.util.repo_path`. Lives in the
    pipeline so callers never have to know about the in-sandbox layout
    constants.
    """
    return repo_path(repo_name)


def map_drafts_to_comment_rows(
    *,
    pr_id: str,
    commit_id: str,
    comments: Sequence[CodeCommentDraft],
) -> list[CodeComment]:
    """Translate :class:`CodeCommentDraft` objects into ORM rows.

    Each draft becomes a :class:`CodeComment` keyed to ``(pr_id,
    commit_id)`` with ``state=ACTIVE``. The agent's severity / side
    strings are coerced into the corresponding enums; a bad value
    raises ``ValueError`` here (this is a programmer error, not a
    pipeline failure mode).
    """
    rows: list[CodeComment] = []
    for draft in comments:
        rows.append(
            CodeComment(
                id=uuidToStr(),
                pr_id=pr_id,
                commit_id=commit_id,
                file_name=draft.file_name,
                comment=draft.comment,
                severity=CommentSeverity(draft.severity),
                from_line=draft.from_line,
                to_line=draft.to_line,
                side=CommentSide(draft.side),
                node_type=draft.node_type,
                state=CommentState.ACTIVE,
            )
        )
    return rows


def flatten_review_error_to_message(error: ReviewPipelineError) -> str:
    """Convert any :class:`ReviewPipelineError` variant to a one-liner.

    Pure: single ``match`` over the closed union. Exhaustive by
    construction; a new variant forces a pyright error here.
    """
    match error:
        case RepoNotFound(repo_id):
            return f"repo {repo_id!r} not found"
        case NoActiveSandbox(user_id, repo_id):
            return f"no active sandbox for user {user_id!r} repo {repo_id!r}"
        case SandboxConnectFailed(_, _, sandbox_id, cause):
            return f"failed to connect sandbox {sandbox_id!r}: {cause}"
        case DiffUnavailable(_, base_sha, head_sha, cause):
            return f"diff unavailable ({base_sha}...{head_sha}): {cause}"
        case ReviewAgentCrashed(cause):
            return f"review agent crashed: {cause}"
        case ReviewAgentReturnedNoStructuredResponse(message_kinds):
            return (
                "review agent returned no structured response "
                f"(messages={list(message_kinds)})"
            )
        case GitHubReviewPostFailed(owner, repo, pr_number, cause):
            return f"github review post failed for {owner}/{repo}#{pr_number}: {cause}"
        case GitHubAuthFailed(installation_id, cause):
            return f"github auth failed for installation {installation_id}: {cause}"
        case GitHubRateLimited(installation_id, cause):
            return f"github rate limited for installation {installation_id}: {cause}"
        case GitHubPRNotFound(owner, repo, pr_number):
            return f"github pr not found: {owner}/{repo}#{pr_number}"
        case GitHubCommentPostFailed(file_name, line, cause):
            return f"github comment post failed for {file_name}:{line}: {cause}"


def truncate_command_output(raw: str, *, max_chars: int = 500) -> str:
    """Trim a command's stderr/stdout tail for inclusion in an error."""
    cleaned = (raw or "").strip()
    return cleaned[:max_chars]


def classify_diff_exit_code(
    *, exit_code: int, output_tail: str
) -> Result[None, DiffUnavailable]:
    """Map a ``git diff`` exit code to ``Result[None, DiffUnavailable]``."""
    if exit_code == 0:
        return Ok(None)
    return Err(
        DiffUnavailable(
            repo_id="",
            base_sha="",
            head_sha="",
            cause=f"git diff exited {exit_code}: {output_tail}",
        )
    )


def build_chat_model(
    *,
    provider: LLMProviderStr,
    base_url: str | None,
    api_key: str,
    model: str,
) -> BaseChatModel:
    """Construct a langchain chat model from the four LLM params.

    Pure factory — no I/O, no settings reads. The API key is wrapped
    in :class:`pydantic.SecretStr` to satisfy each provider's typed
    ``api_key`` parameter (langchain rejects bare ``str`` keys at
    type-check time). ``base_url`` is forwarded to providers that
    accept it (``None`` is a no-op for the others). Unknown providers
    raise ``ValueError``; this is a programmer error, not a pipeline
    failure mode.
    """
    secret: SecretStr = SecretStr(api_key)
    if provider == "openai":
        return ChatOpenAI(model=model, api_key=secret, base_url=base_url)
    if provider == "anthropic":
        # `timeout` and `stop` are pydantic Field aliases for
        # `default_request_timeout` and `stop_sequences`; both default
        # to ``None`` at runtime, but pyright's pydantic-aware checker
        # doesn't always pick that up from the alias. Pass them
        # explicitly so the call type-checks.
        return ChatAnthropic(
            model_name=model,
            api_key=secret,
            base_url=base_url,
            timeout=None,
            stop=None,
        )
    if provider == "google":
        return ChatGoogleGenerativeAI(model=model, api_key=secret)


def _extract_message_kinds(messages: object) -> tuple[str, ...]:
    """Return ``(type,)`` for each message in a deepagents messages list.

    Tolerant of any non-list input (returns an empty tuple) and of
    messages without a string ``type`` attribute.
    """
    if not isinstance(messages, list):
        return ()
    kinds: list[str] = []
    for message in messages:
        kind = getattr(message, "type", None)
        if isinstance(kind, str):
            kinds.append(kind)
    return tuple(kinds)


def parse_review_response(
    result: object,
) -> Result[ReviewResult, ReviewAgentReturnedNoStructuredResponse]:
    """Extract and validate the agent's ``structured_response`` payload.

    Pure: takes the full ``agent.ainvoke()`` result, returns ``Ok``
    with a validated :class:`ReviewResult` or ``Err`` with the variant
    that names the message kinds the agent did produce.
    """
    if not isinstance(result, dict):
        return Err(
            ReviewAgentReturnedNoStructuredResponse(
                message_kinds=_extract_message_kinds(result)
            )
        )
    structured = result.get("structured_response")
    if structured is None:
        return Err(
            ReviewAgentReturnedNoStructuredResponse(
                message_kinds=_extract_message_kinds(result.get("messages"))
            )
        )
    return Ok(ReviewResult.model_validate(structured))


# --------------------------------------------------------------------------- #
# Ring 2 — DB + sandbox shell                                                 #
# --------------------------------------------------------------------------- #


async def get_repo_record(
    *,
    gh_repo_id: int,
    repository: Repository[RepoModel],
) -> Result[RepoModel, RepoNotFound]:
    """Fetch the local :class:`Repo` row by its GitHub-side id.

    Returns ``Err(RepoNotFound)`` when no row matches.
    """
    record = await repository.find_by_field(RepoModel.github_repo_id, gh_repo_id)
    if record is None:
        return Err(RepoNotFound(repo_id=str(gh_repo_id)))
    return Ok(record)


async def get_sandbox(
    *,
    user_id: str,
    repo_id: str,
    repository: Repository[SandboxModel],
    spec: E2BSandboxSpec,
) -> Result[E2BSandbox, NoActiveSandbox | SandboxConnectFailed]:
    """Look up the active sandbox row and connect to the E2B handle.

    "Active" means ``state in {STARTED, PAUSED, STOPPED}`` — any state
    except ``DELETED`` or ``ARCHIVED``. If multiple rows match (data
    integrity issue, but possible) the first one wins and the rest
    are logged.

    Returns:

    - ``Err(NoActiveSandbox)`` when no row matches.
    - ``Err(SandboxConnectFailed)`` when the row exists but the E2B
      ``connect`` call raises.
    """
    sb_record = await repository.find_by_field(SandboxModel.repo_id, repo_id)

    if sb_record is None:
        return Err(NoActiveSandbox(user_id=user_id, repo_id=repo_id))

    try:
        connected = await E2BSandbox.connect(
            sandbox_id=sb_record.id,
            sandbox_name=sb_record.sandbox_name,
            repo_id=repo_id,
            user_id=user_id,
            spec=spec,
            timeout=60 * 60,
            api_key=spec.api_key,
        )
    except Exception as exc:
        log.exception(
            "failed to connect sandbox: user_id=%s repo_id=%s sandbox_id=%s",
            user_id,
            repo_id,
            sb_record.id,
        )
        return Err(
            SandboxConnectFailed(
                user_id=user_id,
                repo_id=repo_id,
                sandbox_id=sb_record.id,
                cause=f"{type(exc).__name__}: {exc}",
            )
        )
    return Ok(connected)


async def get_diff(
    *,
    sandbox: BaseSandbox,
    repo_id: str,
    repo_path_str: str,
    pr_number: int,
    base_sha: str,
    head_sha: str,
) -> Result[str, DiffUnavailable]:
    """Fetch the unified diff for a PR inside the already-cloned sandbox.

    Best-effort ``git fetch origin`` (a failure is logged at ``warning``
    and we proceed) followed by ``git diff <base>...<head>``. Returns
    ``Err(DiffUnavailable)`` with the truncated stderr when ``git
    diff`` exits non-zero.
    """
    fetch = await sandbox.execute(
        "git fetch origin",
        cwd=repo_path_str,
        timeout=120,
    )
    if fetch.exit_code != 0:
        log.warning(
            "git fetch origin failed (continuing): pr_number=%s exit_code=%s stderr=%s",
            pr_number,
            fetch.exit_code,
            fetch.stderr,
        )

    diff_result = await sandbox.execute(
        f"git diff {base_sha}...{head_sha}",
        cwd=repo_path_str,
        timeout=120,
    )
    classification = classify_diff_exit_code(
        exit_code=diff_result.exit_code,
        output_tail=truncate_command_output(
            diff_result.stderr or diff_result.stdout or ""
        ),
    )
    if isinstance(classification, Err):
        return Err(
            DiffUnavailable(
                repo_id=repo_id,
                base_sha=base_sha,
                head_sha=head_sha,
                cause=classification.error.cause,
            )
        )
    return Ok(diff_result.stdout or "")


# --------------------------------------------------------------------------- #
# Ring 2 — agent factory                                                      #
# --------------------------------------------------------------------------- #


def get_review_agent(
    *,
    system_prompt: str,
    subagents: Sequence[SubAgent],
    backend: AsyncE2BSandbox,
    model: BaseChatModel,
) -> DeepAgentGraph:
    """Compose the review deep-agent graph.

    Pure factory — no I/O, no session. The caller owns the connected
    ``backend`` (an :class:`AsyncE2BSandbox` wrapping the E2B handle)
    and the ``model`` (a langchain chat model). The returned graph
    is invoked once per review by :func:`run`.
    """
    log.info(
        "building review deep agent: model=%s subagents=%d",
        getattr(model, "model_name", "<unknown>"),
        len(subagents),
    )
    return create_deep_agent(
        model=model,
        system_prompt=system_prompt,
        subagents=list(subagents),
        backend=backend,
        response_format=ReviewResult,
    )


# --------------------------------------------------------------------------- #
# Ring 3 — persistence shell                                                  #
# --------------------------------------------------------------------------- #


async def _upsert_pull_request(
    session: AsyncSession,
    *,
    repo_id: str,
    github_pr_id: int,
    number: int,
    base_branch: str,
    base_sha: str,
    head_branch: str,
    head_sha: str,
    title: str,
    body: str,
    author: str,
    status: PRStatus,
) -> PullRequest:
    """Insert or update a :class:`PullRequest` row keyed on
    ``(repo_id, number)``.

    On update, the SHAs and branches are refreshed. On insert, the
    author / title / body are left empty — the webhook is the source
    of truth for those, and :func:`run` only needs the SHAs and
    branches to do its work.
    """
    existing = (
        await session.exec(
            select(PullRequest).where(
                PullRequest.repo_id == repo_id,
                PullRequest.number == number,
            )
        )
    ).first()

    now = datetime.now(UTC)
    if existing is not None:
        existing.base_branch = base_branch
        existing.base_sha = base_sha
        existing.head_branch = head_branch
        existing.head_sha = head_sha
        existing.updated_at = now
        existing.title = title
        existing.body = body
        existing.author = author
        existing.status = status
        session.add(existing)
        await session.commit()
        log.info(
            "updated pull request: pr_id=%s repo_id=%s number=%s",
            existing.id,
            repo_id,
            number,
        )
        return existing

    pr = PullRequest(
        id=uuidToStr(),
        repo_id=repo_id,
        number=number,
        author=author,
        title=title,
        body=body,
        status=status,
        base_branch=base_branch,
        base_sha=base_sha,
        head_branch=head_branch,
        head_sha=head_sha,
    )
    session.add(pr)
    await session.commit()
    await session.refresh(pr)
    log.info(
        "inserted pull request: pr_id=%s repo_id=%s number=%s github_pr_id=%s",
        pr.id,
        repo_id,
        number,
        github_pr_id,
    )
    return pr


async def _persist_review_summary(
    session: AsyncSession,
    *,
    pr_id: str,
    commit_id: str,
    result: ReviewResult,
) -> ReviewSummary:
    """Insert a single :class:`ReviewSummary` row."""
    summary = ReviewSummary(
        pr_id=pr_id,
        commit_id=commit_id,
        summary=result.summary,
        verdict=ReviewVerdict(result.verdict),
    )
    session.add(summary)
    await session.flush()
    await session.refresh(summary)
    log.info(
        "persisted review summary: summary_id=%s pr_id=%s verdict=%s",
        summary.id,
        pr_id,
        summary.verdict,
    )
    return summary


async def _persist_code_comments(
    session: AsyncSession,
    *,
    pr_id: str,
    commit_id: str,
    comments: Sequence[CodeCommentDraft],
) -> list[CodeComment]:
    """Insert one :class:`CodeComment` row per draft finding."""
    rows = map_drafts_to_comment_rows(
        pr_id=pr_id, commit_id=commit_id, comments=comments
    )

    # TODO improve this query

    if not rows:
        log.info("no code comments to persist (pr_id=%s)", pr_id)
        return []

    session.add_all(rows)
    await session.flush()
    for row in rows:
        await session.refresh(row)

    log.info(
        "persisted %d code comment(s): pr_id=%s commit_id=%s",
        len(rows),
        pr_id,
        commit_id,
    )
    return rows


# --------------------------------------------------------------------------- #
# Ring 2 — orchestrator                                                       #
# --------------------------------------------------------------------------- #


async def run(input: Input) -> Result[ReviewRunResult, ReviewPipelineError]:
    """Run one review end-to-end.

    Sequence:

    1. Resolve the :class:`Repo` row.
    2. Look up + connect the active sandbox.
    3. Fetch the unified diff.
    4. Upsert the :class:`PullRequest` row.
    5. Build the chat model and the deep-agent graph.
    6. Invoke the agent.
    7. Persist the :class:`ReviewSummary` and :class:`CodeComment` rows.
    8. Post review to GitHub (if ``post_to_github=True``).
    9. Stop the sandbox (always, even on early ``Err`` returns).

    Each stage returns a ``Result``; an ``Err`` short-circuits to the
    caller. The single outermost ``try / except`` catches anything
    that escapes the typed pipeline (programmer bugs, unhandled SDK
    errors, ``asyncio.CancelledError``) and folds it into
    ``Err(ReviewAgentCrashed)``.
    """
    sandbox: E2BSandbox | None = None
    try:
        repo_repository: Repository[RepoModel] = Repository(RepoModel, input.session)
        sandbox_repository: Repository[SandboxModel] = Repository(
            SandboxModel, input.session
        )

        # 1. repo
        repo_result = await get_repo_record(
            gh_repo_id=input.gh_repo_id, repository=repo_repository
        )

        if isinstance(repo_result, Err):
            return Err(repo_result.error)
        repo: RepoModel = repo_result.value

        # 2. sandbox
        sandbox_result = await get_sandbox(
            user_id=input.user_id,
            repo_id=repo.id,
            repository=sandbox_repository,
            spec=input.spec,
        )

        if isinstance(sandbox_result, Err):
            return Err(sandbox_result.error)
        sandbox = sandbox_result.value

        # 3. diff
        diff_result = await get_diff(
            sandbox=sandbox,
            repo_id=repo.id,
            repo_path_str=get_repo_path(repo.repo_name),
            pr_number=input.pr_number,
            base_sha=input.base_sha,
            head_sha=input.head_sha,
        )

        if isinstance(diff_result, Err):
            return Err(diff_result.error)
        diff: str = diff_result.value

        # 4. upsert pull request
        pr = await _upsert_pull_request(
            input.session,
            repo_id=repo.id,
            github_pr_id=input.pr_id,
            number=input.pr_number,
            base_branch=input.branch,
            base_sha=input.base_sha,
            head_branch=input.head_branch,
            head_sha=input.head_sha,
            title=input.title,
            body=input.body,
            author=input.author,
            status=input.status,
        )
        commit_id: str = input.head_sha

        # 5. build the agent
        chat_model: BaseChatModel = build_chat_model(
            provider=input.provider,
            base_url=input.llm_baseurl,
            api_key=input.llm_api_key,
            model=input.llm_model,
        )
        backend: AsyncE2BSandbox = AsyncE2BSandbox(sandbox=sandbox.sandbox)
        agent: DeepAgentGraph = get_review_agent(
            system_prompt=assemble_orchestrator_system_prompt(),
            subagents=assemble_review_subagents(),
            backend=backend,
            model=chat_model,
        )

        # 6. invoke
        user_prompt = assemble_user_prompt(
            repo_name=repo.repo_name,
            repo_id=repo.id,
            user_id=input.user_id,
            pr_number=input.pr_number,
            diff=diff,
        )
        log.info(
            "invoking review agent: repo=%s user=%s pr_number=%s",
            repo.repo_name,
            input.user_id,
            input.pr_number,
        )
        try:
            raw = await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_prompt}]}
            )
        except Exception as exc:
            log.exception(
                "review agent crashed: repo=%s pr_number=%s",
                repo.repo_name,
                input.pr_number,
            )
            return Err(ReviewAgentCrashed(cause=f"{type(exc).__name__}: {exc}"))

        parsed = parse_review_response(raw)
        if isinstance(parsed, Err):
            return Err(parsed.error)

        review: ReviewResult = parsed.value

        # 7. persist
        review_summary = await _persist_review_summary(
            input.session,
            pr_id=pr.id,
            commit_id=commit_id,
            result=review,
        )
        code_comment_rows = await _persist_code_comments(
            input.session,
            pr_id=pr.id,
            commit_id=commit_id,
            comments=review.comments,
        )

        await input.session.commit()

        # 8. post to GitHub (optional)
        if input.post_to_github and input.github_installation_id:
            try:
                github_client = installation_client(input.github_installation_id)
                github_result = await post_review_and_update_db(
                    session=input.session,
                    github_client=github_client,
                    owner=repo.repo_owner,
                    repo=repo.repo_name,
                    pr_number=input.pr_number,
                    commit_id=commit_id,
                    result=review,
                    review_summary=review_summary,
                    code_comments=code_comment_rows,
                )

                if isinstance(github_result, Err):
                    return Err(github_result.error)

                log.info(
                    "Successfully posted review to GitHub: owner=%s repo=%s pr_number=%s",
                    repo.repo_owner,
                    repo.repo_name,
                    input.pr_number,
                )
            except Exception as exc:
                log.exception(
                    "GitHub posting failed: owner=%s repo=%s pr_number=%s exc=%s",
                    repo.repo_owner,
                    repo.repo_name,
                    input.pr_number,
                    exc,
                )
                # Don't fail the entire pipeline if GitHub posting fails
                # The review is persisted locally, can be retried later
                pass

        # 9. result
        return Ok(
            ReviewRunResult(
                pr_id=pr.id,
                commit_id=commit_id,
                result=review,
            )
        )
    except Exception as exc:
        log.exception(
            "review pipeline crashed: gh_repo_id=%s pr_number=%s",
            input.gh_repo_id,
            input.pr_number,
        )
        return Err(ReviewAgentCrashed(cause=f"{type(exc).__name__}: {exc}"))
    finally:
        if sandbox is not None:
            try:
                await sandbox.stop()
            except Exception:
                log.exception(
                    "failed to stop sandbox: gh_repo_id=%s pr_number=%s",
                    input.gh_repo_id,
                    input.pr_number,
                )


__all__: list[str] = [
    "DeepAgentGraph",
    "DiffProviderFn",
    "Input",
    "LLMProviderStr",
    "ReviewAgentRunnerFn",
    "ReviewRunResult",
    "assemble_orchestrator_system_prompt",
    "assemble_review_subagents",
    "assemble_user_prompt",
    "build_chat_model",
    "classify_diff_exit_code",
    "flatten_review_error_to_message",
    "get_diff",
    "get_repo_path",
    "get_repo_record",
    "get_review_agent",
    "get_sandbox",
    "map_drafts_to_comment_rows",
    "parse_review_response",
    "run",
    "truncate_command_output",
]
