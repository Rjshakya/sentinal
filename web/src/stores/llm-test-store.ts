import { create } from "zustand";

import type { LlmConfigPayload } from "@/lib/api";

export type LlmTestStatus = { ok: boolean; message: string };

type LlmTestStore = {
  testedPayload: LlmConfigPayload | null;
  result: LlmTestStatus | null;
  recordTest: (payload: LlmConfigPayload, result: LlmTestStatus) => void;
  clearTest: () => void;
};

export const useLlmTestStore = create<LlmTestStore>((set) => ({
  testedPayload: null,
  result: null,
  recordTest: (payload, result) => set({ testedPayload: payload, result }),
  clearTest: () => set({ testedPayload: null, result: null }),
}));

export function payloadsMatch(
  a: LlmConfigPayload | null,
  b: LlmConfigPayload,
): boolean {
  if (!a) return false;
  return (
    a.provider === b.provider &&
    a.model_id === b.model_id &&
    a.base_url === b.base_url &&
    a.api_key === b.api_key
  );
}
