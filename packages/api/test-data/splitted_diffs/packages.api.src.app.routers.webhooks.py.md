### packages/api/src/app/routers/webhooks.py

```diff

index cede0d6..8504395 100644
--- a/packages/api/src/app/routers/webhooks.py
+++ b/packages/api/src/app/routers/webhooks.py
@@ -24,11 +24,6 @@ Verifies the ``X-Hub-Signature-256`` HMAC against
   25    25    :func:`app.services.pr_issue_comment.handle_issue_comment_created`,
   26    26    which dispatches a durable DBOS workflow that classifies the
   27    27    comment and (on match) dispatches the inner review workflow.
   28       -- ``push`` -> delegate to
   29       -  :func:`app.services.indexing.incremental.handle_push_event`, which
   30       -  dispatches the incremental indexing workflow for default-branch
   31       -  pushes (reconciles the repo's LanceDB dataset with the changed
   32       -  files).
   33    28  - anything else -> 202 with a log line.
   34    29  
   35    30  The handler sits outside AuthMiddleware's protected prefixes: GitHub
@@ -53,7 +48,6 @@ from app.core.config import settings
   54    49  from app.core.db import async_session_maker
   55    50  from app.models.installation import Installation
   56    51  from app.models.repo import Repo
   57       -from app.services.indexing.incremental import handle_push_event
   58    52  from app.services.pr_issue_comment import handle_issue_comment_created
   59    53  from app.services.review import webhook as review_webhook
   60    54  from app.utils.util import uuidToStr
@@ -86,6 +80,23 @@ def _verify_signature(secret: str, body: bytes, signature_header: str | None) ->
   87    81      return hmac.compare_digest(provided, expected)
   88    82  
   89    83  
         84 +# --------------------------------------------------------------------------- #
         85 +# summarizers                                                                  #
         86 +# --------------------------------------------------------------------------- #
         87 +
         88 +
         89 +def _summarize_pull_request(payload: dict[str, Any]) -> dict[str, Any]:
         90 +    repo = payload.get("repository") or {}
         91 +    owner = (repo.get("owner") or {}).get("login")
         92 +    name = repo.get("name")
         93 +    pr = payload.get("pull_request") or {}
         94 +    return {
         95 +        "repository": f"{owner}/{name}" if owner and name else None,
         96 +        "number": pr.get("number"),
         97 +        "sender": (payload.get("sender") or {}).get("login"),
         98 +    }
         99 +
        100 +
   90   101  # --------------------------------------------------------------------------- #
   91   102  # user resolution                                                              #
   92   103  # --------------------------------------------------------------------------- #
@@ -188,7 +199,8 @@ async def _handle_installation_deleted(payload: dict[str, Any]) -> Response:
  189   200          await session.commit()
  190   201  
  191   202      log.info(
  192       -        "github_webhook: installation.deleted dropped (github_installation_id=%s)",
        203 +        "github_webhook: installation.deleted dropped %d row(s) "
        204 +        "(github_installation_id=%s)",
  193   205          gh_installation_id,
  194   206      )
  195   207      return Response(status_code=202)
@@ -412,11 +424,6 @@ async def github_webhook(
  413   425              )
  414   426          return Response(status_code=202)
  415   427  
  416       -    if event == "push":
  417       -        ack = await handle_push_event(payload, delivery)
  418       -        log.info("github_webhook: push handled: %s", ack.model_dump_json())
  419       -        return Response(status_code=202)
  420       -
  421   428      log.info(
  422   429          "github_webhook: ignored event=%s (delivery=%s, bytes=%d)",
  423   430          event,

```
