### packages/api/src/app/services/llm_config/__init__.py

```diff

index b60a39a..7489eb6 100644
--- a/packages/api/src/app/services/llm_config/__init__.py
+++ b/packages/api/src/app/services/llm_config/__init__.py
@@ -29,7 +29,7 @@ from datetime import UTC, datetime
   30    30  from uuid import UUID
   31    31  
   32    32  from deepagents import create_deep_agent
   33       -from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
         33 +from langchain.agents.structured_output import ToolStrategy
   34    34  from pydantic import BaseModel, Field
   35    35  from sqlmodel import select
   36    36  from sqlmodel.ext.asyncio.session import AsyncSession
@@ -136,12 +136,10 @@ async def test_user_llm_config(
  137   137  
  138   138      try:
  139   139          chat = build_chat_model(config=config)
  140       -
  141   140          agent = create_deep_agent(
  142   141              model=chat,
  143       -            response_format=ProviderStrategy(ProbeResult),
  144       -            system_prompt=""" Respond ONLY with a json object matching this schema: '
  145       -    '{"reply": "<string>"}. No other text.""",
        142 +            response_format=ToolStrategy(ProbeResult),
        143 +            system_prompt="give response in reply field of ProbeResult",
  146   144          )
  147   145          result = await agent.ainvoke(
  148   146              {"messages": [{"role": "user", "content": "Hi there"}]}

```
