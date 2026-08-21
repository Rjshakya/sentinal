import { IconGitPullRequest, IconMessage2, IconSparkles, type Icon } from "@tabler/icons-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

import { SectionHeading } from "./-section-heading";

const features: { icon: Icon; title: string; description: string }[] = [
  { icon: IconSparkles, title: "Context-aware reviews", description: "reviewpr understands your repository, not just the patch in front of it." },
  { icon: IconMessage2, title: "Feedback where it matters", description: "Clear comments land directly on the changed lines your team needs to inspect." },
  { icon: IconGitPullRequest, title: "A verdict for every PR", description: "Severity-tagged findings and a concise summary make every pull request easier to triage." },
];

export function FeaturesSection() {
  return (
    <section id="product" className="border-y border-border bg-muted/30 px-5 py-20 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <div className="max-w-2xl">
          <SectionHeading
            align="left"
            eyebrow="Review signal, not noise"
            title="A sharper way to move every pull request forward."
          />
        </div>
        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {features.map(({ icon: Icon, title, description }) => (
            <Card key={title}>
              <CardHeader>
                <span className="mb-3 grid size-10 place-items-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="size-5" />
                </span>
                <CardTitle>{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription>{description}</CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
