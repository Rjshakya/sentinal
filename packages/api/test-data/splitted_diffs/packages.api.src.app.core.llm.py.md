### packages/api/src/app/core/llm.py

```diff

index faa2d9e..01e286b 100644
--- a/packages/api/src/app/core/llm.py
+++ b/packages/api/src/app/core/llm.py
@@ -221,19 +221,13 @@ def build_chat_model(
  222   222      if (
  223   223          provider == "openai"
  224   224          and config.model_id
  225       -        and config.model_id.startswith("gpt-5.6")
        225 +        and config.model_id.startswith(("gpt-5.6"))
  226   226      ):
  227   227          extra = {
  228   228              "use_responses_api": True,
  229   229              "output_version": "responses/v1",
  230   230          }
  231   231  
  232       -    if config.model_id.startswith("deepseek"):
  233       -        extra["extra_body"] = {"response_format": {"type": "json_object"}}
  234       -
  235       -    # if config.model_id.startswith("deepseek"):
  236       -    #     extra["extra_body"] = {"thinking": {"type": "disabled"}}
  237       -
  238   232      return init_chat_model(
  239   233          model=config.model,
  240   234          api_key=SecretStr(config.api_key) if config.api_key else None,

```
