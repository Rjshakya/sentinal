import type { ReactNode } from "react";
import {
  IconBrandGithub,
  IconBug,
  IconCircleCheck,
  IconCube,
  IconShield,
  IconSparkles,
} from "@tabler/icons-react";

import { SectionHeading } from "./-section-heading";

function StepFrame({ src, children }: { src: string; children: ReactNode }) {
  return (
    <div className="relative aspect-square overflow-hidden bg-illustration p-4 shadow-sm ring-1 ring-border-illustration">
      <img src={src} alt="" className="absolute inset-0 h-full w-full object-cover" />
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="w-full scale-75  ">{children}</div>
      </div>
    </div>
  );
}

function TerminalPanel() {
  return (
    <div className="bg-background ring-2 ring-ring/30  rounded-[12px]  drop-shadow-xl drop-shadow-accent/15  ">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <IconCube className="size-3.5" />
          sandbox — e2b
        </div>
        <div className="flex gap-1">
          <div className="size-1 rounded-full bg-foreground/20" />
          <div className="size-1 rounded-full bg-foreground/20" />
          <div className="size-1 rounded-full bg-foreground/20" />
        </div>
      </div>
      <div className="space-y-1 p-4 font-mono text-xs leading-6">
        <p>
          <span className="text-primary">$</span> sentinel sandbox create --repo acme/api
        </p>
        <p className="text-emerald-600">✓ sandbox ready — sb-8f3a2</p>
        <p>
          <span className="text-primary">$</span> git clone git@github.com:acme/api.git
        </p>
        <p className="text-muted-foreground">Cloning into &apos;api&apos;... done.</p>
        <p className="text-emerald-600">✓ cloned in 2.4s — full context loaded</p>
      </div>
    </div>
  );
}

const agents = [
  {
    icon: IconShield,
    name: "Security",
    pill: "P1",
    pillClass: "text-destructive ring-destructive/30",
  },
  {
    icon: IconBug,
    name: "Correctness",
    pill: "P2",
    pillClass: "text-amber-600 ring-amber-600/30 dark:text-amber-500",
  },
  {
    icon: IconSparkles,
    name: "Style",
    pill: "P3",
    pillClass: "text-muted-foreground ring-foreground/15",
  },
];

function AgentsPanel() {
  return (
    <div className="bg-background ring-2 ring-ring/30 rounded-[12px]  drop-shadow-xl drop-shadow-accent/15  ">
      <div className="border-b px-3 py-2 font-mono text-xs text-muted-foreground">
        review:acme-api:234:a1b2c3d
      </div>
      <div className="grid gap-3 p-3 sm:grid-cols-2">
        <div className="ring-1 ring-border">
          <div className="border-b px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
            src/app/core/config.py
          </div>
          <div className="space-y-0.5 p-3 font-mono text-[11px] leading-5">
            <p className="text-rose-600/80">- api_key = os.getenv(&quot;OPENAI_KEY&quot;)</p>
            <p className="text-emerald-600/80">+ api_key = load_secret(&quot;openai&quot;)</p>
            <p className="text-muted-foreground"> max_retries = 3</p>
            <p className="text-emerald-600/80">+ rate_limit_rps = 2</p>
          </div>
        </div>
        <div className="flex flex-col justify-center gap-2">
          {agents.map(({ icon: Icon, name, pill, pillClass }) => (
            <div
              key={name}
              className="flex items-center justify-between bg-illustration px-3 py-2 ring-1 ring-border-illustration"
            >
              <div className="flex items-center gap-2 text-xs font-medium">
                <Icon className="size-3.5 text-muted-foreground" />
                {name}
              </div>
              <span
                className={`rounded-full px-2 py-0.5 font-mono text-[10px] font-semibold ring-1 ${pillClass}`}
              >
                {pill}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const summaryBullets = [
  <>
    Token refresh now handles expiry —{" "}
    <span className="text-primary font-mono">src/auth.py:42</span>
  </>,
  <>
    Rate limits enforced per tenant —{" "}
    <span className="text-primary font-mono">src/github.py:88</span>
  </>,
];

const comments = [
  {
    pill: "P1",
    pillClass: "text-destructive ring-destructive/30",
    text: "Unescaped input in query builder",
    ref: "auth.py:42",
  },
  {
    pill: "P2",
    pillClass: "text-amber-600 ring-amber-600/30 dark:text-amber-500",
    text: "Retry loop can exceed rate limits",
    ref: "github.py:88",
  },
  {
    pill: "P3",
    pillClass: "text-muted-foreground ring-foreground/15",
    text: "Variable naming inconsistent with codebase",
    ref: "main.py:17",
  },
];

function ReviewPanel() {
  return (
    <div className="bg-background ring-2  ring-ring/30  rounded-[12px]  drop-shadow-xl drop-shadow-accent/15 ">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <IconBrandGithub className="size-4" />
          acme/api <span className="text-muted-foreground">#234</span>
        </div>
        <span className="rounded-full bg-primary/10 px-2.5 py-0.5 font-mono text-[10px] font-semibold text-primary ring-1 ring-primary/30">
          REQUEST CHANGES
        </span>
      </div>
      <div className="space-y-3 p-4">
        <div className="space-y-1.5 bg-illustration p-3 text-xs leading-5 ring-1 ring-border-illustration">
          {summaryBullets.map((bullet, i) => (
            <p key={i}>• {bullet}</p>
          ))}
        </div>
        {comments.map(({ pill, pillClass, text, ref }) => (
          <div key={text} className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-2">
              <span
                className={`mt-0.5 rounded-full px-2 py-0.5 font-mono text-[10px] font-semibold ring-1 ${pillClass}`}
              >
                {pill}
              </span>
              <p className="text-xs leading-5">{text}</p>
            </div>
            <span className="font-mono text-[10px] text-muted-foreground">{ref}</span>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between border-t px-4 py-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-emerald-600">
          <IconCircleCheck className="size-3.5" />
          Posted to GitHub
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">gh-review-102938</span>
      </div>
    </div>
  );
}

const steps = [
  {
    number: "01",
    title: "Clone the repo in an isolated sandbox",
    description:
      "Sentinel spins up a fresh, disposable sandbox and clones your repository — every review runs with full codebase context.",
    image: "/reviewpr-bg.png",
    panel: <TerminalPanel />,
  },
  {
    number: "02",
    title: "Run parallel agents against the PR",
    description:
      "Security, correctness, and style specialists read the diff alongside the code in parallel, anchoring every finding to a real line.",
    image: "/reviewpr-bg-2.png",
    panel: <AgentsPanel />,
  },
  {
    number: "03",
    title: "Push review to GitHub",
    description:
      "Severity-tagged inline comments, a grounded summary, and a clear verdict land directly on your pull request.",
    image: "/reviewpr-bg-3.png",
    panel: <ReviewPanel />,
  },
];

export function WorkflowSection() {
  return (
    <section id="how-it-works" className="px-5 py-20 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <SectionHeading eyebrow="How reviewpr works" title="Clone. Review. Merge. Done." />
        <div className="mt-16 grid grid-cols-1  md:grid-cols-3 gap-4">
          {steps.map((step) => (
            <div key={step.number} className="flex flex-col gap-8 md:gap-12">
              <StepFrame src={step.image}>{step.panel}</StepFrame>
              <div>
                <span className="font-mono text-xs font-semibold text-primary">{step.number}</span>
                <h3 className="mt-4 font-heading text-xl font-semibold tracking-tight">
                  {step.title}
                </h3>
                <p className="mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                  {step.description}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
