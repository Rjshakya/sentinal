import { IconAlertTriangle, IconCheck } from "@tabler/icons-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { CommonCard } from "@/components/common-card";
import { CardDescription, CardTitle } from "@/components/ui/card";
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
import { Skeleton } from "@/components/ui/skeleton";
import type { PiConfig, PiConfigPayload } from "@/lib/api";
import { usePiConfig, usePiModels, usePiProviders, useSavePiConfig } from "@/lib/pi";

export type PiConfigCardProps = {
  existing: PiConfig | null;
};

type SaveStatus = { ok: boolean; message: string } | null;

export function PiConfigCard({ existing }: PiConfigCardProps) {
  const { data: providers, isLoading: providersLoading } = usePiProviders();
  const [provider, setProvider] = useState<string>(existing?.provider ?? "");
  const [modelId, setModelId] = useState<string>(existing?.model_id ?? "");
  const [apiKey, setApiKey] = useState<string>("");
  const [touched, setTouched] = useState<boolean>(false);
  const [status, setStatus] = useState<SaveStatus>(null);

  const { data: modelsData, isLoading: modelsLoading } = usePiModels(
    provider === "" ? null : provider,
  );
  const save = useSavePiConfig();

  const selectedProvider = useMemo(
    () => providers?.find((p) => p.piProvider === provider) ?? null,
    [providers, provider],
  );
  const oauthOnly = selectedProvider !== null && selectedProvider.apiKeyEnvs.length === 0;
  const manualEntry = modelsData?.manualEntry === true;

  const formValid =
    provider.length > 0 &&
    modelId.trim().length > 0 &&
    apiKey.trim().length > 0 &&
    !oauthOnly;

  const payload = useMemo<PiConfigPayload>(
    () => ({ provider, model_id: modelId.trim(), api_key: apiKey }),
    [provider, modelId, apiKey],
  );

  function handleSave() {
    setTouched(true);
    if (!formValid) return;
    setStatus(null);
    save.mutate(payload, {
      onSuccess: (data) => {
        if (data.success) {
          toast.success("Pi model config saved");
          setStatus({
            ok: true,
            message: data.test_result.response ?? "Connected.",
          });
        } else {
          const message = data.error ?? data.test_result.exception ?? "Save failed";
          toast.error(message);
          setStatus({ ok: false, message });
        }
      },
      onError: (err) => {
        toast.error(err.message);
        setStatus({ ok: false, message: err.message });
      },
    });
  }

  if (providersLoading) return <Skeleton className="h-64 w-full" />;

  return (
    <CommonCard
      className="drop-shadow-sm"
      headerClassName="flex-col items-stretch p-1 gap-0"
      bodyClassName="space-y-4 "
      footerClassName=" flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between"
      header={
        <>
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <CardTitle>Pi model</CardTitle>
            </div>
            {existing ? (
              <span className="flex items-center gap-2 border-2 border-dashed px-2 py-1 rounded-md  text-green-500">
                <IconCheck className="size-3" />
                <p className="text-[10px]">configured</p>
              </span>
            ) : (
              <span className="flex items-center gap-2 bg-muted px-2 py-1">
                <IconCheck className="size-3.5" />
                <p className="text-xs">not configured</p>
              </span>
            )}
          </div>
          <CardDescription>
            The provider and model the pi agent will run with inside the sandbox.
            Saving tests the key first — it can take a minute.
          </CardDescription>
        </>
      }
      body={
        <>
          <div className="grid gap-4 ">
            <Label htmlFor="pi-provider">Provider</Label>
            <Select
              value={provider === "" ? undefined : provider}
              onValueChange={(v) => {
                if (v == null) return;
                setProvider(v);
                setModelId("");
              }}
            >
              <SelectTrigger id="pi-provider" className="w-full text-muted-foreground ">
                <SelectValue placeholder="Select a provider  " />
              </SelectTrigger>
              <SelectContent>
                {providers?.map((opt) => (
                  <SelectItem key={opt.piProvider} value={opt.piProvider}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {oauthOnly && (
              <p className="text-destructive text-xs">
                This provider needs an OAuth sign-in — an API key is not supported.
              </p>
            )}
          </div>

          <div className="grid gap-4 ">
            <Label htmlFor="pi-model">Model</Label>
            {manualEntry || provider === "" ? (
              <Input
                id="pi-model"
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
                placeholder={
                  provider === "" ? "Select a provider first" : "e.g. kimi-k2-thinking"
                }
                disabled={provider === ""}
                autoComplete="off"
                className=" text-muted-foreground"
              />
            ) : modelsLoading ? (
              <Skeleton className="h-9 w-full" />
            ) : (
              <Select
                value={modelId === "" ? undefined : modelId}
                onValueChange={(v) => {
                  if (v == null) return;
                  setModelId(v);
                }}
              >
                <SelectTrigger id="pi-model" className="w-full text-muted-foreground ">
                  <SelectValue placeholder="Select a model  " />
                </SelectTrigger>
                <SelectContent>
                  {modelsData?.models.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.name} ({m.id})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="grid gap-4 ">
            <Label htmlFor="pi-api-key">API key</Label>
            <div className="space-y-1">
              <Input
                id="pi-api-key"
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

          {touched && !formValid && !oauthOnly && (
            <p className="text-destructive text-xs">
              Provider, model, and API key are required.
            </p>
          )}

          {status && (
            <>
              <Separator />
              <div
                className={
                  status.ok
                    ? "text-foreground flex items-start gap-2 text-xs"
                    : "text-destructive flex items-start gap-2 text-xs"
                }
              >
                {status.ok ? (
                  <IconCheck className="mt-0.5 size-3.5 shrink-0" />
                ) : (
                  <IconAlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                )}
                <span className="wrap-break-word">{status.message}</span>
              </div>
            </>
          )}
        </>
      }
      footer={
        <>
          <span />
          <div className="flex justify-end gap-2">
            <Button onClick={handleSave} disabled={!formValid || save.isPending}>
              {save.isPending ? "Saving…" : existing ? "update" : "Save"}
            </Button>
          </div>
        </>
      }
    />
  );
}

export function PiConfigSection() {
  const { data: existing, isLoading } = usePiConfig();
  if (isLoading) return <Skeleton className="h-64 w-full" />;
  return <PiConfigCard existing={existing ?? null} />;
}
