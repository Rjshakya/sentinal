### packages/api/src/app/services/agent/setup_workflow/steps/mint_installation_token.py

```diff

new file mode 100644
index 0000000..c03f226
--- /dev/null
+++ b/packages/api/src/app/services/agent/setup_workflow/steps/mint_installation_token.py
@@ -0,0 +1,66 @@
          2 +"""Step 2: mint a fresh GitHub installation access token.
          3 +
          4 +The token is short-lived (E2B caches it for us via the App's
          5 +:class:`githubkit.auth.AppAuthStrategy`, but the API call here is
          6 +explicit so the workflow captures a token for the clone step and
          7 +for the sandbox's ``GITHUB_TOKEN`` env var).
          8 +"""
          9 +
         10 +from __future__ import annotations
         11 +
         12 +import logging
         13 +
         14 +from dbos import DBOS
         15 +
         16 +from app.core.github_app import mint_installation_token
         17 +from app.services.agent.setup_workflow.errors import InstallTokenMintError
         18 +
         19 +log = logging.getLogger(__name__)
         20 +
         21 +
         22 +def _should_retry_setup(exc: BaseException) -> bool:
         23 +    from app.services.agent.setup_workflow.errors import TransientSetupError
         24 +
         25 +    return isinstance(exc, TransientSetupError)
         26 +
         27 +
         28 +@DBOS.step(
         29 +    retries_allowed=True,
         30 +    max_attempts=3,
         31 +    should_retry=_should_retry_setup,
         32 +)
         33 +async def mint_installation_token_step(*, github_installation_id: int) -> str:
         34 +    """Mint a fresh installation access token for ``github_installation_id``.
         35 +
         36 +    Wraps :func:`app.core.github_app.mint_installation_token` and
         37 +    converts any exception into :class:`InstallTokenMintError` so the
         38 +    workflow's typed-error boundary stays clean. Retried up to
         39 +    ``max_attempts`` times on transient SDK failures (network blips,
         40 +    GitHub 5xx, etc.).
         41 +
         42 +    Returns:
         43 +        The fresh installation access token as a plain ``str``. The
         44 +        caller is responsible for embedding it in the clone URL via
         45 +        :func:`app.services.agent.setup_workflow._helpers.build_authenticated_clone_url`.
         46 +
         47 +    Raises:
         48 +        InstallTokenMintError: the underlying
         49 +            :func:`mint_installation_token` raised. Retried by DBOS
         50 +            on :class:`TransientSetupError`; final on persistent
         51 +            failure.
         52 +    """
         53 +    try:
         54 +        token = await mint_installation_token(github_installation_id)
         55 +    except Exception as exc:
         56 +        log.exception(
         57 +            "mint_installation_token failed: installation_id=%s",
         58 +            github_installation_id,
         59 +        )
         60 +        raise InstallTokenMintError(
         61 +            cause=f"{type(exc).__name__}: {exc}"
         62 +        ) from exc
         63 +    return token
         64 +
         65 +
         66 +__all__ = ["mint_installation_token_step"]
         67 +

```
