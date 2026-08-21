import { IconCheck } from "@tabler/icons-react";

import { SectionHeading } from "./-section-heading";

export function SecuritySection() {
  return (
    <section id="why" className="px-5 pb-20 lg:px-8">
      <div className="mx-auto grid max-w-6xl gap-10 bg-muted/40 p-7 ring-1 ring-foreground/10 md:grid-cols-[1fr_auto] md:items-center md:p-10">
        <div>
          <SectionHeading
            align="left"
            eyebrow="Catch issues before they ship"
            title="The cheapest bug is the one caught before merge."
            description="reviewpr reads the full diff against your codebase context and flags real issues — security holes, logic bugs, style drift — before a human reviewer ever opens the PR."
          />
        </div>
        <div className="grid gap-3 text-sm">
          {["Findings anchored to real lines", "Security, correctness, and style — triaged by severity", "Every PR reviewed, even the 3 AM drafts"].map(
            (item) => (
              <div key={item} className="flex items-center gap-2">
                <IconCheck className="size-4 text-primary" />
                {item}
              </div>
            )
          )}
        </div>
      </div>
    </section>
  );
}
