### packages/api/src/app/services/pr_issue_comment/helpers.py

```diff

index af41d6b..3ce71d2 100644
--- a/packages/api/src/app/services/pr_issue_comment/helpers.py
+++ b/packages/api/src/app/services/pr_issue_comment/helpers.py
@@ -96,7 +96,6 @@ def validate_comment_payload(
   97    97          "repo_owner": owner,
   98    98          "repo_name": repository.get("name"),
   99    99          "gh_repo_id": repository.get("id"),
  100       -        "default_branch": repository.get("default_branch"),
  101   100          "pr_number": issue.get("number"),
  102   101          "pr_author_login": issue_user.get("login"),
  103   102          "commenter_login": comment_user.get("login"),
@@ -261,9 +260,7 @@ def build_review_workflow_input(
  262   261      ``base_branch``, ``head_branch``, ``title``, ``body``, ``author``,
  263   262      ``state``, ``merged``) come from
  264   263      :func:`app.services.pr_issue_comment.steps.fetch_pr_state.fetch_pr_state_step`
  265       -    — the comment payload does not carry them. ``default_branch`` is
  266       -    the exception: it is read straight off the payload's
  267       -    ``repository.default_branch`` via :class:`IssueCommentTriggerInput`.
        264 +    — the comment payload does not carry them.
  268   265      """
  269   266      return ReviewWorkflowInput(
  270   267          user_id=user_id,
@@ -271,7 +268,6 @@ def build_review_workflow_input(
  272   269          pr_id=gh_pr_id,
  273   270          pr_number=trigger.pr_number,
  274   271          branch=base_branch,
  275       -        default_branch=trigger.default_branch,
  276   272          base_sha=base_sha,
  277   273          head_sha=head_sha,
  278   274          head_branch=head_branch,
@@ -279,7 +275,6 @@ def build_review_workflow_input(
  280   276          body=body or "",
  281   277          title=title or "",
  282   278          status=_classify_pr_status(state, merged),
  283       -        trigger="comment",
  284   279          llm_config=llm_config,
  285   280          post_to_github=True,
  286   281          github_installation_id=trigger.installation_id,

```
