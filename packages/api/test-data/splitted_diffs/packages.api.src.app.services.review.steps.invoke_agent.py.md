### packages/api/src/app/services/review/steps/invoke_agent.py

```diff

index 52d8e11..5c1dbea 100644
--- a/packages/api/src/app/services/review/steps/invoke_agent.py
+++ b/packages/api/src/app/services/review/steps/invoke_agent.py
@@ -41,9 +41,9 @@ from __future__ import annotations
   42    42  import json
   43    43  import logging
   44    44  import re
   45       -from collections.abc import Callable, Sequence
   46       -from datetime import UTC, datetime
   47       -from typing import Any
         45 +from collections.abc import Sequence
         46 +from datetime import datetime, timezone
         47 +from typing import Any, Callable
   48    48  
   49    49  import sentry_sdk
   50    50  from dbos import DBOS
@@ -578,7 +578,7 @@ def combine_agent_outcomes(
  579   579              workflow_id=workflow_id,
  580   580              failed_agents=failures,
  581   581              succeeded_agents=list(successes.keys()),
  582       -            occurred_at=datetime.now(UTC),
        582 +            occurred_at=datetime.now(timezone.utc),
  583   583          )
  584   584          _capture_review_agents_error_to_sentry(err)
  585   585          raise err

```
