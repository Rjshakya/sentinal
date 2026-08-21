### packages/api/src/app/services/review/webhook.py

```diff

index 3d0bcc0..82eb01d 100644
--- a/packages/api/src/app/services/review/webhook.py
+++ b/packages/api/src/app/services/review/webhook.py
@@ -69,13 +69,12 @@ class WebhookAck(BaseModel):
   70    70  
   71    71  
   72    72  class PRReviewInput(BaseModel):
   73       -    """Flat, typed pr_payload of a verified ``pull_request`` payload."""
         73 +    """Flat, typed view of a verified ``pull_request`` payload."""
   74    74  
   75    75      gh_repo_id: int
   76    76      gh_pr_id: int
   77    77      number: int
   78    78      base_branch: str
   79       -    default_branch: str | None = None
   80    79      base_sha: str
   81    80      head_branch: str
   82    81      head_sha: str
@@ -106,7 +105,7 @@ def _classify_status(pr: dict[str, Any]) -> str | None:
  107   106  
  108   107  
  109   108  def extract_payload(payload: dict[str, Any]) -> PRReviewInput | None:
  110       -    """Project the GitHub ``pull_request`` payload onto a typed pr_payload.
        109 +    """Project the GitHub ``pull_request`` payload onto a typed view.
  111   110  
  112   111      Returns ``None`` on any malformed input — the orchestrator folds
  113   112      that into a ``skip_reason="malformed_payload"`` ack. Never raises.
@@ -122,7 +121,6 @@ def extract_payload(payload: dict[str, Any]) -> PRReviewInput | None:
  123   122          "gh_pr_id": pr.get("id"),
  124   123          "number": pr.get("number"),
  125   124          "base_branch": base.get("ref"),
  126       -        "default_branch": repo.get("default_branch"),
  127   125          "base_sha": base.get("sha"),
  128   126          "head_branch": head.get("ref"),
  129   127          "head_sha": head.get("sha"),
@@ -164,28 +162,27 @@ async def resolve_llm_config(user_id: str) -> LLMConfig:
  165   163  
  166   164  
  167   165  def build_review_workflow_input(
  168       -    pr_payload: PRReviewInput,
        166 +    view: PRReviewInput,
  169   167      *,
  170   168      user_id: str,
  171   169      llm_config: LLMConfig,
  172   170      github_installation_id: int | None = None,
  173   171      post_to_github: bool = False,
  174   172  ) -> ReviewWorkflowInput:
  175       -    """Translate the webhook pr_payload into a serializable workflow input."""
        173 +    """Translate the webhook view into a serializable workflow input."""
  176   174      return ReviewWorkflowInput(
  177   175          user_id=user_id,
  178       -        gh_repo_id=pr_payload.gh_repo_id,
  179       -        pr_id=pr_payload.gh_pr_id,
  180       -        pr_number=pr_payload.number,
  181       -        branch=pr_payload.base_branch,
  182       -        default_branch=pr_payload.default_branch,
  183       -        base_sha=pr_payload.base_sha,
  184       -        head_sha=pr_payload.head_sha,
  185       -        head_branch=pr_payload.head_branch,
  186       -        author=pr_payload.author,
  187       -        title=pr_payload.title,
  188       -        body=pr_payload.body or "",
  189       -        status=pr_payload.status,
        176 +        gh_repo_id=view.gh_repo_id,
        177 +        pr_id=view.gh_pr_id,
        178 +        pr_number=view.number,
        179 +        branch=view.base_branch,
        180 +        base_sha=view.base_sha,
        181 +        head_sha=view.head_sha,
        182 +        head_branch=view.head_branch,
        183 +        author=view.author,
        184 +        title=view.title,
        185 +        body=view.body or "",
        186 +        status=view.status,
  190   187          llm_config=llm_config,
  191   188          post_to_github=post_to_github,
  192   189          github_installation_id=github_installation_id,
@@ -291,8 +288,8 @@ async def handle_pull_request_opened(
  292   289              skip_reason="malformed_installation",
  293   290          )
  294   291  
  295       -    pr_payload = extract_payload(payload)
  296       -    if pr_payload is None:
        292 +    view = extract_payload(payload)
        293 +    if view is None:
  297   294          return WebhookAck(
  298   295              accepted=False,
  299   296              action="opened",
@@ -307,8 +304,8 @@ async def handle_pull_request_opened(
  308   305              "github_installation_id=%s gh_repo_id=%s number=%s",
  309   306              delivery,
  310   307              installation_id,
  311       -            pr_payload.gh_repo_id,
  312       -            pr_payload.number,
        308 +            view.gh_repo_id,
        309 +            view.number,
  313   310          )
  314   311          return WebhookAck(
  315   312              accepted=False,
@@ -317,14 +314,14 @@ async def handle_pull_request_opened(
  318   315              skip_reason="unowned_installation",
  319   316          )
  320   317  
  321       -    repo_id = await resolve_repo_id(pr_payload.gh_repo_id)
        318 +    repo_id = await resolve_repo_id(view.gh_repo_id)
  322   319      if repo_id is None:
  323   320          log.info(
  324   321              "review.webhook: skip (repo not configured): delivery=%s "
  325   322              "gh_repo_id=%s number=%s",
  326   323              delivery,
  327       -            pr_payload.gh_repo_id,
  328       -            pr_payload.number,
        324 +            view.gh_repo_id,
        325 +            view.number,
  329   326          )
  330   327          return WebhookAck(
  331   328              accepted=False,
@@ -339,8 +336,8 @@ async def handle_pull_request_opened(
  340   337              "delivery=%s gh_repo_id=%s number=%s llm_configured=%s "
  341   338              "sandbox_configured=%s",
  342   339              delivery,
  343       -            pr_payload.gh_repo_id,
  344       -            pr_payload.number,
        340 +            view.gh_repo_id,
        341 +            view.number,
  345   342              settings.llm_configured,
  346   343              settings.sandbox_configured,
  347   344          )
@@ -355,7 +352,7 @@ async def handle_pull_request_opened(
  356   353      post_to_github = installation_id is not None
  357   354  
  358   355      workflow_input = build_review_workflow_input(
  359       -        pr_payload,
        356 +        view,
  360   357          user_id=user_id,
  361   358          llm_config=llm_config,
  362   359          github_installation_id=installation_id,
@@ -364,8 +361,8 @@ async def handle_pull_request_opened(
  365   362  
  366   363      workflow_id = create_review_workflow_id(
  367   364          repo_id=repo_id,
  368       -        pr_number=pr_payload.number,
  369       -        head_sha=pr_payload.head_sha,
        365 +        pr_number=view.number,
        366 +        head_sha=view.head_sha,
  370   367      )
  371   368  
  372   369      log.info(
@@ -373,9 +370,9 @@ async def handle_pull_request_opened(
  374   371          "gh_repo_id=%s number=%s head_sha=%s post_to_github=%s",
  375   372          delivery,
  376   373          workflow_id,
  377       -        pr_payload.gh_repo_id,
  378       -        pr_payload.number,
  379       -        pr_payload.head_sha,
        374 +        view.gh_repo_id,
        375 +        view.number,
        376 +        view.head_sha,
  380   377          post_to_github,
  381   378      )
  382   379  

```
