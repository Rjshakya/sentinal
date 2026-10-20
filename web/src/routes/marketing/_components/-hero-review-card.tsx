import { IconChevronDown, IconDots } from "@tabler/icons-react";

const diffLines = [
  { no: "64", code: "def handleOpencodeLLMCtx(llm_ctx: LLMCtx, commitId: str) -> LLMCtx:" },
  { no: "65", code: '"""Tag opencode-gateway LLM contexts with the run\'s session header."""' },
  { no: "66", code: "ctx = llm_ctx" },
  { no: "67", code: 'if ctx is not None and "opencode" in str(ctx.baseUrl):' },
];

export function HeroReviewCard() {
  return (
    <div className="w-full h-full flex flex-col  overflow-hidden   bg-[#0b0e13] text-white shadow-2xl ring-1 ring-white/15">



      {/* File header */}
      <div className="w-full  flex items-center gap-2 border-b border-white/10 bg-black/50 px-4 py-2.5">
        <IconChevronDown className="size-4 shrink-0 text-white/70" />
        <span className="truncate font-mono text-[13px] text-white/90">
          packages/api/src/app/_common.py
        </span>
      </div>

      {/* Diff */}
      <div className="overflow-x-auto bg-emerald-950/50 font-mono text-[12.5px] leading-6">
        {diffLines.map((line) => (
          <div key={line.no} className="flex min-w-max">
            <span className="w-10 shrink-0 pr-2 text-right text-white/40 select-none">
              {line.no}
            </span>
            <span className="pr-1 text-emerald-400/80 select-none">+</span>
            <span className="pr-4 whitespace-pre text-emerald-100/90">{line.code}</span>
          </div>
        ))}
      </div>

      {/* Author row */}
      <div className="flex min-w-0 items-center gap-2 border-y border-white/10 px-4 py-3 text-sm">
        <span className="truncate font-medium tracking-tight">reviewpr-bot</span>
        <span className="shrink-0 rounded-full border border-white/20 px-1.5 py-px text-[11px] font-medium text-white/70">
          Bot
        </span>
        <span className="truncate text-white/50">on Sept 17</span>
        <IconDots className="ml-auto size-4 shrink-0 text-white/40" />
      </div>

      {/* Body */}
      <div className="min-w-0 space-y-4 px-4 py-5 sm:px-5">
        <p className="text-[17px] leading-7 font-medium tracking-tight text-balance">
          Opencode session tagging overwrites configured LLM headers in place
        </p>
        <ul className="list-disc space-y-2.5 pl-5 text-[13.5px] leading-6 break-words text-white/80">
          <li className="min-w-0">
            <span className="font-mono text-[12.5px] break-all text-white/90">
              packages/api/src/app/workflows/triggers/_common.py:68
            </span>{" "}
            assigns <span className="font-mono text-[12.5px] break-all">ctx.defaultHeaders</span> ={" "}
            <span className="font-mono text-[12.5px] break-all">{'{"x-opencode-session": …}'}</span>,
            discarding existing entries.
          </li>
          <li className="min-w-0">
            <span className="font-mono text-[12.5px] break-all text-white/90">
              packages/api/src/app/services/llm/service.py:108,152
            </span>{" "}
            populate <span className="font-mono text-[12.5px] break-all">defaultHeaders</span> from{" "}
            <span className="font-mono text-[12.5px] break-all">settings.llm_default_headers</span> (gateway
            ids / tags per{" "}
            <span className="font-mono text-[12.5px] break-all">
              packages/api/src/app/core/config.py:227
            </span>
            ).
          </li>
          <li className="min-w-0">
            <span className="font-mono text-[12.5px] break-all text-white/90">
              packages/api/src/app/workflows/triggers/review.py:254,401
            </span>{" "}
            calls this on every trigger right after{" "}
            <span className="font-mono text-[12.5px] break-all">resolveLlmCtx</span>, so opencode-gateway
            runs silently lose those headers;{" "}
            <span className="font-mono text-[12.5px] break-all">ctx = llm_ctx</span> also mutates the
            caller&apos;s LLMCtx instead of copying.
          </li>
        </ul>
        <p className="min-w-0 text-[13.5px] leading-6 break-words text-white/80">
          Fix: Merge instead of replace on a copy, e.g.{" "}
          <span className="font-mono text-[12.5px] break-all text-white/90">
            return ctx.model_copy(update={"{"}&quot;defaultHeaders&quot;: {"{...}"}ctx.defaultHeaders,
            &quot;x-opencode-session&quot;: f&apos;session-{"{commitId[:6]}"}&apos;{"}"}
            {"}"})
          </span>
          .
        </p>
      </div>

      {/* Reply */}
      <div className="flex min-w-0 items-center gap-3 border-t border-white/10 px-4 py-3">
        <img src="/pp-icon.png" alt="" className="size-7 shrink-0 rounded-full object-cover" />
        <div className="min-w-0 flex-1 truncate rounded-full border border-white/15 bg-white/5 px-4 py-2 text-sm text-white/40">
          Reply...
        </div>
      </div>
    </div>
  );
}
