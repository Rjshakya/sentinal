### packages/api/src/app/services/review/workflow.py

```diff

index d617047..8ee4232 100644
--- a/packages/api/src/app/services/review/workflow.py
+++ b/packages/api/src/app/services/review/workflow.py
@@ -20,24 +20,10 @@ Design notes:
   21    21  - The E2B sandbox object is never passed between steps. Only the
   22    22    sandbox id travels through the workflow; each step reconnects by
   23    23    id.
   24       -- The ``review`` lifecycle row
   25       -  (:func:`app.services.review.steps.review_run_steps`) records one
   26       -  row per run: ``RUNNING`` once the PR row exists, ``SUCCESS`` after
   27       -  the GitHub post completes, ``FAILED`` on any terminal exception.
   28       -  The ``mark_*`` steps are durable — DBOS retries them on transient
   29       -  DB failures and they raise
   30       -  :class:`app.services.review.errors.ReviewRunUpdateError`; a
   31       -  persistent mirror failure marks the workflow ERROR rather than
   32       -  silently leaving the row stuck in ``RUNNING``. The row is created
   33       -  inside the ``try`` so the sandbox ``finally`` also covers a running
   34       -  step that raises.
   35       -- GitHub posting is awaited before the review is marked stopped, so
   36       -  the ``review`` row's ``github_review_id`` is populated on the
   37       -  success path. The post is still a separate durable workflow
         24 +- GitHub posting is a separate durable workflow
   38    25    (:func:`app.services.github.workflow.post_review_to_github_workflow`)
   39       -  that can be retried / restarted independently without re-running
   40       -  the LLM agent; it never raises, so an awaited post failure does
   41       -  not fail the review.
         26 +  so it can be retried / restarted independently without re-running
         27 +  the LLM agent.
   42    28  - Token-usage accounting happens at the end of the local pipeline
   43    29    via :func:`app.services.review.steps.persist_usage.persist_review_usage_tx`,
   44    30    which writes a :class:`app.models.review_usage.ReviewUsage` row
@@ -63,7 +49,6 @@ from app.services.review.steps import (
   64    50      resolve_repo_tx,
   65    51      resolve_sandbox_step,
   66    52      stop_sandbox_step,
   67       -    update_repo_step,
   68    53      upsert_pull_request_tx,
   69    54  )
   70    55  from app.services.review.steps.invoke_agent import (
@@ -72,15 +57,8 @@ from app.services.review.steps.invoke_agent import (
   73    58      invoke_summary_agent_step,
   74    59  )
   75    60  from app.services.review.steps.persist_usage import sum_total_usages
   76       -from app.services.review.steps.review_run_steps import (
   77       -    build_error_context,
   78       -    mark_review_is_errored_step,
   79       -    mark_review_is_running_step,
   80       -    mark_review_is_stopped_step,
   81       -)
   82    61  from app.services.review.workflow_types import (
   83    62      PostReviewInput,
   84       -    PostReviewResult,
   85    63      ReviewRunResult,
   86    64      ReviewWorkflowInput,
   87    65  )
@@ -105,65 +83,11 @@ async def review_workflow(input: ReviewWorkflowInput) -> ReviewRunResult:
  106    84      successful :func:`app.services.review.steps.resolve_sandbox_step`.
  107    85      If :func:`app.services.review.steps.resolve_sandbox_step` itself
  108    86      raises, there is no connected sandbox to stop.
  109       -
  110       -    The ``review`` lifecycle row runs alongside: the row is created
  111       -    in ``RUNNING`` after the PR row exists, flipped to ``SUCCESS`` by
  112       -    :func:`app.services.review.steps.review_run_steps.mark_review_is_stopped_step`
  113       -    at the end of the success path, and flipped to ``FAILED`` by
  114       -    :func:`app.services.review.steps.review_run_steps.mark_review_is_errored_step`
  115       -    on any terminal exception (which is then re-raised). The
  116       -    ``mark_*`` steps are durable and raise
  117       -    :class:`app.services.review.errors.ReviewRunUpdateError` on
  118       -    failure; the ``except`` block guards the errored step so a
  119       -    failure while recording the error never masks the original
  120       -    exception.
  121    87      """
  122    88      repo = await resolve_repo_tx(input.gh_repo_id)
  123    89      sandbox = await resolve_sandbox_step(user_id=input.user_id, repo_id=repo.id)
  124    90  
  125       -    workflow_id = DBOS.workflow_id or "<no-workflow-id>"
  126       -    review_id: str | None = None
  127       -
  128    91      try:
  129       -        pr_id = await upsert_pull_request_tx(
  130       -            repo_id=repo.id,
  131       -            github_pr_id=input.pr_id,
  132       -            number=input.pr_number,
  133       -            base_branch=input.branch,
  134       -            base_sha=input.base_sha,
  135       -            head_branch=input.head_branch,
  136       -            head_sha=input.head_sha,
  137       -            title=input.title,
  138       -            body=input.body,
  139       -            author=input.author,
  140       -            status=input.status,
  141       -        )
  142       -
  143       -        review_id = await mark_review_is_running_step(
  144       -            user_id=input.user_id,
  145       -            repo_id=repo.id,
  146       -            gh_repo_id=input.gh_repo_id,
  147       -            pr_id=pr_id,
  148       -            pr_number=input.pr_number,
  149       -            commit_id=input.head_sha,
  150       -            base_sha=input.base_sha,
  151       -            trigger=input.trigger,
  152       -            sandbox_id=sandbox.sandbox_id,
  153       -            workflow_id=workflow_id,
  154       -            llm_provider=input.llm_config.provider,
  155       -            llm_model=input.llm_config.model_id,
  156       -            llm_base_url=input.llm_config.base_url,
  157       -        )
  158       -
  159       -        await update_repo_step(
  160       -            sandbox_id=sandbox.sandbox_id,
  161       -            sandbox_name=sandbox.sandbox_name,
  162       -            repo_id=repo.id,
  163       -            repo_name=repo.repo_name,
  164       -            user_id=input.user_id,
  165       -            default_branch=input.default_branch or repo.default_branch,
  166       -        )
  167       -
  168    92          await fetch_diff_step(
  169    93              sandbox_id=sandbox.sandbox_id,
  170    94              sandbox_name=sandbox.sandbox_name,
@@ -192,6 +116,20 @@ async def review_workflow(input: ReviewWorkflowInput) -> ReviewRunResult:
  193   117              for file_name, entry in parsed_diff["files"].items()
  194   118          }
  195   119  
        120 +        pr_id = await upsert_pull_request_tx(
        121 +            repo_id=repo.id,
        122 +            github_pr_id=input.pr_id,
        123 +            number=input.pr_number,
        124 +            base_branch=input.branch,
        125 +            base_sha=input.base_sha,
        126 +            head_branch=input.head_branch,
        127 +            head_sha=input.head_sha,
        128 +            title=input.title,
        129 +            body=input.body,
        130 +            author=input.author,
        131 +            status=input.status,
        132 +        )
        133 +
  196   134          agent_results = await asyncio.gather(
  197   135              invoke_summary_agent_step(
  198   136                  sandbox_id=sandbox.sandbox_id,
@@ -223,21 +161,18 @@ async def review_workflow(input: ReviewWorkflowInput) -> ReviewRunResult:
  224   162              repo_id=repo.id,
  225   163              user_id=input.user_id,
  226   164              llm_config=input.llm_config,
  227       -            workflow_id=workflow_id,
        165 +            workflow_id=DBOS.workflow_id or "<no-workflow-id>",
  228   166          )
  229   167  
  230   168          filtered_review = filter_drafts(review, hunk_map)
  231   169  
  232   170          summary_id = await persist_review_summary_tx(
  233   171              pr_id=pr_id,
  234       -            review_id=review_id,
  235   172              commit_id=input.head_sha,
  236   173              result=filtered_review,
  237   174          )
  238       -
  239   175          await persist_code_comments_tx(
  240   176              pr_id=pr_id,
  241       -            review_id=review_id,
  242   177              commit_id=input.head_sha,
  243   178              comments=[c.model_dump(mode="json") for c in filtered_review.comments],
  244   179          )
@@ -245,10 +180,8 @@ async def review_workflow(input: ReviewWorkflowInput) -> ReviewRunResult:
  246   181          input_tokens, output_tokens, total_tokens, input_token_details = (
  247   182              sum_total_usages(usages)
  248   183          )
  249       -
  250   184          await persist_review_usage_tx(
  251   185              pr_id=pr_id,
  252       -            review_id=review_id,
  253   186              user_id=input.user_id,
  254   187              pr_number=input.pr_number,
  255   188              repo_id=repo.id,
@@ -258,12 +191,8 @@ async def review_workflow(input: ReviewWorkflowInput) -> ReviewRunResult:
  259   192              output_tokens=output_tokens,
  260   193              total_tokens=total_tokens,
  261   194              input_token_details=input_token_details,
  262       -            llm_model_id=input.llm_config.model_id,
  263       -            llm_provider=input.llm_config.provider,
  264       -            llm_base_url=input.llm_config.base_url,
  265   195          )
  266   196  
  267       -        github_review_id: str | None = None
  268   197          if input.post_to_github and input.github_installation_id is not None:
  269   198              post_input = PostReviewInput(
  270   199                  repo_id=repo.id,
@@ -278,23 +207,14 @@ async def review_workflow(input: ReviewWorkflowInput) -> ReviewRunResult:
  279   208  
  280   209              post_workflow_id = f"post:{repo.id}:{input.pr_number}:{input.head_sha[:7]}"
  281   210              with SetWorkflowID(post_workflow_id):
  282       -                post_handle = await DBOS.start_workflow_async(
        211 +                await DBOS.start_workflow_async(
  283   212                      post_review_to_github_workflow, post_input
  284   213                  )
  285       -                post_result: PostReviewResult = await post_handle.get_result()
  286       -            if post_result.github_review_id is not None:
  287       -                github_review_id = str(post_result.github_review_id)
  288       -
  289       -        await mark_review_is_stopped_step(
  290       -            review_id=review_id,
  291       -            comment_count=len(filtered_review.comments),
  292       -            github_review_id=github_review_id,
  293       -        )
  294   214  
  295   215          log.info(
  296   216              "workflow: stopping workflow: workflow_id=%s "
  297   217              "gh_repo_id=%s number=%s head_sha=%s",
  298       -            workflow_id,
        218 +            DBOS.workflow_id,
  299   219              input.gh_repo_id,
  300   220              input.pr_number,
  301   221              input.head_sha,
@@ -307,22 +227,6 @@ async def review_workflow(input: ReviewWorkflowInput) -> ReviewRunResult:
  308   228              usages=usages,
  309   229          )
  310   230  
  311       -    except BaseException as exc:
  312       -        try:
  313       -            await mark_review_is_errored_step(
  314       -                review_id=review_id,
  315       -                error_name=type(exc).__name__,
  316       -                error_message=str(exc),
  317       -                error_context=build_error_context(exc),
  318       -            )
  319       -        except Exception:
  320       -            log.exception(
  321       -                "workflow: failed to record review error review_id=%s workflow_id=%s",
  322       -                review_id,
  323       -                workflow_id,
  324       -            )
  325       -        raise
  326       -
  327   231      finally:
  328   232          await stop_sandbox_step(
  329   233              sandbox_id=sandbox.sandbox_id,

```
