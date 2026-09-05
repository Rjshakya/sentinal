import {
  IconAlertTriangle,
  IconCheck,
  IconCircleDashed,
  IconKey,
  IconRefresh,
} from "@tabler/icons-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import type { LlmConfig, LlmConfigPayload } from "@/lib/api";
import { useTestLlmConfig, useUpdateLlmConfig } from "@/lib/llm";
import { payloadsMatch, useLlmTestStore, type LlmTestStatus } from "@/stores/llm-test-store";

const PROVIDER_OPTIONS: { value: string; label: string }[] = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "google_genai", label: "Google (Gemini)" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "groq", label: "Groq" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "mistralai", label: "Mistral" },
  { value: "xai", label: "xAI (Grok)" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "other", label: "Other (custom prefix)" },
];

const OTHER_VALUE = "other";
const COMMON_VALUES = new Set([
  "openai",
  "anthropic",
  "google_genai",
  "openrouter",
  "groq",
  "deepseek",
  "mistralai",
  "xai",
  "ollama",
]);

export type LlmConfigCardProps = {
  existing: LlmConfig | null;
};

export function LlmConfigCard({ existing }: LlmConfigCardProps) {
  const [providerSelect, setProviderSelect] = useState<string>(
    existing && !COMMON_VALUES.has(existing.provider)
      ? OTHER_VALUE
      : (existing?.provider ?? "openai"),
  );
  const [customProvider, setCustomProvider] = useState<string>(
    existing && !COMMON_VALUES.has(existing.provider) ? existing.provider : "",
  );
  const [modelId, setModelId] = useState<string>(existing?.model_id ?? "");
  const [baseUrl, setBaseUrl] = useState<string>(existing?.base_url ?? "");
  const [apiKey, setApiKey] = useState<string>("");
  const [touched, setTouched] = useState<boolean>(false);

  const { testedPayload, result, recordTest, clearTest } = useLlmTestStore();
  const test = useTestLlmConfig();
  const update = useUpdateLlmConfig();

  const resolvedProvider = providerSelect === OTHER_VALUE ? customProvider.trim() : providerSelect;
  const formValid =
    resolvedProvider.length > 0 &&
    modelId.trim().length > 0 &&
    baseUrl.trim().length > 0 &&
    apiKey.trim().length > 0;

  const payload = useMemo<LlmConfigPayload>(
    () => ({
      provider: resolvedProvider,
      model_id: modelId.trim(),
      base_url: baseUrl.trim(),
      api_key: apiKey,
    }),
    [resolvedProvider, modelId, baseUrl, apiKey],
  );
  const canSave = (payload: LlmConfigPayload) =>
    formValid && payloadsMatch(testedPayload, payload) && result?.ok === true;

  const showTestHint = (payload: LlmConfigPayload) =>
    formValid && (!result || !payloadsMatch(testedPayload, payload) || !result.ok);

  function handleTest() {
    setTouched(true);
    if (!formValid) return;
    clearTest();
    test.mutate(payload, {
      onSuccess: (data) => {
        const status: LlmTestStatus =
          data.success && data.test_result.response
            ? { ok: true, message: `OK: "${data.test_result.response.slice(0, 80)}"` }
            : {
              ok: false,
              message: data.error ?? data.test_result.exception ?? "Test failed",
            };
        recordTest(payload, status);
      },
      onError: (err) => {
        recordTest(payload, { ok: false, message: err.message });
      },
    });
  }

  function handleSave() {
    setTouched(true);
    if (!canSave(payload)) return;
    update.mutate(payload, {
      onSuccess: (data) => {
        if (data.success) {
          toast.success("LLM config saved");
          clearTest();
        } else {
          toast.error(data.error ?? "Could not save LLM config");
        }
      },
      onError: (err) => {
        toast.error(err.message);
      },
    });
  }

  return (
    <Card className="flex flex-col  p-1 gap-1 drop-shadow-sm  ">
      <CardHeader className=" p-1 gap-0">
        <div className="flex items-center justify-between  gap-2">
          <div className="flex items-center  gap-2">
            <CardTitle>LLM provider</CardTitle>
          </div>
          {existing ? (
            <span className=" flex items-center gap-2 px-2 py-1  border-2 border-dashed text-green-500  ">
              <IconCheck className="size-3" />
              <p className="text-[10px]">configured</p>

            </span>
          ) : (
            <span className=" flex items-center gap-2 px-2 py-1  bg-muted   ">
              <IconCheck className="size-3.5" />
              <p className="text-xs">not configured</p>

            </span>
          )}
        </div>
        <CardDescription>
          The chat model Sentinel will use to review your pull requests.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 bg-muted dark:bg-muted p-4 border-t ">
        <div className="grid gap-4 ">
          <Label htmlFor="llm-provider">Provider</Label>
          <div className="space-y-2">
            <Select
              value={providerSelect}
              onValueChange={(v) => {
                if (v == null) return;
                setProviderSelect(v);
                if (v !== OTHER_VALUE) setCustomProvider("");
              }}
            >
              <SelectTrigger id="llm-provider" className="w-full text-muted-foreground ">
                <SelectValue placeholder="Select a provider  " />
              </SelectTrigger>
              <SelectContent>
                {PROVIDER_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {providerSelect === OTHER_VALUE && (
              <Input
                value={customProvider}
                onChange={(e) => setCustomProvider(e.target.value)}
                placeholder="provider prefix (e.g. fireworks)"
                aria-label="Custom provider prefix"
              />
            )}
          </div>
        </div>

        <div className="grid gap-4 ">
          <Label htmlFor="llm-model">Model ID</Label>
          <Input
            id="llm-model"
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            placeholder="e.g. gpt-4o-mini, claude-3-5-sonnet-latest"
            autoComplete="off"
            className=" text-muted-foreground"
          />
        </div>

        <div className="grid gap-4 ">
          <Label htmlFor="llm-base-url">Base URL</Label>
          <Input
            id="llm-base-url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://api.openai.com/v1"
            autoComplete="off"
            className=" text-muted-foreground"
          />
        </div>

        <div className="grid gap-4 ">
          <Label htmlFor="llm-api-key">API key</Label>
          <div className="space-y-1">
            <Input
              id="llm-api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={existing ? "•••••••• (set)" : "sk-…"}
              autoComplete="off"
              className=" text-muted-foreground"
            />
            <p className="text-muted-foreground text-xs">
              The server stores this encrypted at rest. Re-enter the key each time you change it —
              the existing key is never displayed back.
            </p>
          </div>
        </div>

        {touched && !formValid && (
          <p className="text-destructive text-xs">All four fields are required.</p>
        )}

        {result && (
          <>
            <Separator />
            <div
              className={
                result.ok
                  ? "text-foreground flex items-start gap-2 text-xs"
                  : "text-destructive flex items-start gap-2 text-xs"
              }
            >
              {result.ok ? (
                <IconCheck className="mt-0.5 size-3.5 shrink-0" />
              ) : (
                <IconAlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              )}
              <span className="wrap-break-word">{result.message}</span>
            </div>
          </>
        )}
      </CardContent>
      <CardFooter className=" mb-1 bg-muted dark:bg-muted     flex flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
        {showTestHint(payload) ? (
          <p className="text-muted-foreground text-xs">Test the connection before saving.</p>
        ) : (
          <span />
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={handleTest} disabled={!formValid || test.isPending}>
            <IconRefresh />
            {test.isPending ? "Testing…" : "Test connection"}
          </Button>
          <Button onClick={handleSave} disabled={!canSave || update.isPending}>
            {update.isPending ? "Saving…" : existing ? "update" : "Save"}
          </Button>
        </div>
      </CardFooter>
    </Card>
  );
}
