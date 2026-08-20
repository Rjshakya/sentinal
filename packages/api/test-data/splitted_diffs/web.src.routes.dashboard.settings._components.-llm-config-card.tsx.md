### web/src/routes/dashboard/settings/_components/-llm-config-card.tsx

```diff

index d7ed019..f82be21 100644
--- a/web/src/routes/dashboard/settings/_components/-llm-config-card.tsx
+++ b/web/src/routes/dashboard/settings/_components/-llm-config-card.tsx
@@ -142,16 +142,17 @@ export function LlmConfigCard({ existing }: LlmConfigCardProps) {
  143   143    }
  144   144  
  145   145    return (
  146       -    <Card className="flex flex-col  p-1 gap-1 drop-shadow-sm  ">
  147       -      <CardHeader className=" p-4 gap-3 ">
  148       -        <div className="flex items-center  gap-2">
        146 +    <Card className="flex flex-col">
        147 +      <CardHeader>
        148 +        <div className="flex items-start justify-between gap-2">
  149   149            <div className="flex items-center gap-2">
  150       -            <IconKey className="size-4" />
        150 +            <IconKey className="size-5" />
  151   151              <CardTitle>LLM provider</CardTitle>
  152   152            </div>
  153   153            {existing ? (
  154       -            <Badge className="p-1  bg-green-700  ">
  155       -              <IconCheck className="size-3" />
        154 +            <Badge>
        155 +              <IconCheck />
        156 +              Configured
  156   157              </Badge>
  157   158            ) : (
  158   159              <Badge variant="secondary">
@@ -161,11 +162,12 @@ export function LlmConfigCard({ existing }: LlmConfigCardProps) {
  162   163            )}
  163   164          </div>
  164   165          <CardDescription>
  165       -          The chat model Sentinel will use to review your pull requests.
        166 +          The chat model Sentinel uses to review your pull requests. Set an API key once — the
        167 +          server stores it for you and reuses it on every review run.
  166   168          </CardDescription>
  167   169        </CardHeader>
  168       -      <CardContent className="space-y-4 bg-muted dark:bg-muted p-4 border-t ">
  169       -        <div className="grid gap-4 ">
        170 +      <CardContent className="space-y-4">
        171 +        <div className="grid gap-2 sm:grid-cols-[180px_1fr] sm:items-center">
  170   172            <Label htmlFor="llm-provider">Provider</Label>
  171   173            <div className="space-y-2">
  172   174              <Select
@@ -176,8 +178,8 @@ export function LlmConfigCard({ existing }: LlmConfigCardProps) {
  177   179                  if (v !== OTHER_VALUE) setCustomProvider("");
  178   180                }}
  179   181              >
  180       -              <SelectTrigger id="llm-provider" className="w-full text-muted-foreground ">
  181       -                <SelectValue placeholder="Select a provider  " />
        182 +              <SelectTrigger id="llm-provider" className="w-full">
        183 +                <SelectValue placeholder="Select a provider" />
  182   184                </SelectTrigger>
  183   185                <SelectContent>
  184   186                  {PROVIDER_OPTIONS.map((opt) => (
@@ -198,7 +200,7 @@ export function LlmConfigCard({ existing }: LlmConfigCardProps) {
  199   201            </div>
  200   202          </div>
  201   203  
  202       -        <div className="grid gap-4 ">
        204 +        <div className="grid gap-2 sm:grid-cols-[180px_1fr] sm:items-center">
  203   205            <Label htmlFor="llm-model">Model ID</Label>
  204   206            <Input
  205   207              id="llm-model"
@@ -206,11 +208,10 @@ export function LlmConfigCard({ existing }: LlmConfigCardProps) {
  207   209              onChange={(e) => setModelId(e.target.value)}
  208   210              placeholder="e.g. gpt-4o-mini, claude-3-5-sonnet-latest"
  209   211              autoComplete="off"
  210       -            className=" text-muted-foreground"
  211   212            />
  212   213          </div>
  213   214  
  214       -        <div className="grid gap-4 ">
        215 +        <div className="grid gap-2 sm:grid-cols-[180px_1fr] sm:items-center">
  215   216            <Label htmlFor="llm-base-url">Base URL</Label>
  216   217            <Input
  217   218              id="llm-base-url"
@@ -218,11 +219,10 @@ export function LlmConfigCard({ existing }: LlmConfigCardProps) {
  219   220              onChange={(e) => setBaseUrl(e.target.value)}
  220   221              placeholder="https://api.openai.com/v1"
  221   222              autoComplete="off"
  222       -            className=" text-muted-foreground"
  223   223            />
  224   224          </div>
  225   225  
  226       -        <div className="grid gap-4 ">
        226 +        <div className="grid gap-2 sm:grid-cols-[180px_1fr] sm:items-center">
  227   227            <Label htmlFor="llm-api-key">API key</Label>
  228   228            <div className="space-y-1">
  229   229              <Input
@@ -232,7 +232,6 @@ export function LlmConfigCard({ existing }: LlmConfigCardProps) {
  233   233                onChange={(e) => setApiKey(e.target.value)}
  234   234                placeholder={existing ? "•••••••• (set)" : "sk-…"}
  235   235                autoComplete="off"
  236       -              className=" text-muted-foreground"
  237   236              />
  238   237              <p className="text-muted-foreground text-xs">
  239   238                The server stores this encrypted at rest. Re-enter the key each time you change it —
@@ -265,7 +264,7 @@ export function LlmConfigCard({ existing }: LlmConfigCardProps) {
  266   265            </>
  267   266          )}
  268   267        </CardContent>
  269       -      <CardFooter className=" mb-1 bg-muted dark:bg-muted     flex flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
        268 +      <CardFooter className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
  270   269          {showTestHint(payload) ? (
  271   270            <p className="text-muted-foreground text-xs">Test the connection before saving.</p>
  272   271          ) : (
@@ -277,7 +276,7 @@ export function LlmConfigCard({ existing }: LlmConfigCardProps) {
  278   277              {test.isPending ? "Testing…" : "Test connection"}
  279   278            </Button>
  280   279            <Button onClick={handleSave} disabled={!canSave || update.isPending}>
  281       -            {update.isPending ? "Saving…" : existing ? "update" : "Save"}
        280 +            {update.isPending ? "Saving…" : existing ? "Replace" : "Save"}
  282   281            </Button>
  283   282          </div>
  284   283        </CardFooter>

```
