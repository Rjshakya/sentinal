### web/src/lib/api.ts

```diff

index 93c0806..a4a80fd 100644
--- a/web/src/lib/api.ts
+++ b/web/src/lib/api.ts
@@ -124,27 +124,27 @@ export type LlmConfigPayload = {
  125   125  };
  126   126  
  127   127  export type CodeSearchRequest = {
  128       -  owner: string;
  129       -  repo: string;
        128 +  repo_id: string;
        129 +  repo_name: string;
  130   130    query: string;
  131   131    limit?: number;
  132   132  };
  133   133  
  134   134  export type CodeSearchResult = {
  135       -  file_name: string;
  136       -  language: string;
  137       -  start_line: number;
  138       -  end_line: number;
  139       -  node_types: string[];
  140       -  content: string;
  141       -  _relevance_score: number;
        135 +  id?: string | number;
        136 +  file_name?: string;
        137 +  start_line?: number;
        138 +  end_line?: number;
        139 +  content?: string;
        140 +  node_types?: string | string[] | null;
        141 +  language?: string | null;
        142 +  _relevance_score?: number;
  142   143  };
  143   144  
  144   145  export type CodeSearchResponse = {
  145       -  owner: string;
  146       -  repo: string;
  147       -  query: string;
  148       -  results: CodeSearchResult[];
        146 +  repo_name?: string;
        147 +  query?: string;
        148 +  results?: CodeSearchResult[];
  149   149  };
  150   150  
  151   151  export type UserRepo = {
@@ -156,7 +156,6 @@ export type UserRepo = {
  157   157    url: string | null;
  158   158    private: boolean;
  159   159    default_branch: string | null;
  160       -  is_indexed: boolean;
  161   160    created_at: string;
  162   161    updated_at: string;
  163   162  };
@@ -213,7 +212,7 @@ export const apiClient = {
  214   213        body: JSON.stringify(payload),
  215   214      }),
  216   215    codeSearch: (payload: CodeSearchRequest) =>
  217       -    request<CodeSearchResponse>("/search", {
        216 +    request<CodeSearchResponse>("/ai/code/search", {
  218   217        method: "POST",
  219   218        headers: { "Content-Type": "application/json" },
  220   219        body: JSON.stringify(payload),

```
