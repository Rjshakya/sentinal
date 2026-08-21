import { Button } from "@/components/ui/button";

import { SectionHeading } from "./-section-heading";
import { Link } from "@tanstack/react-router";
import { IconArrowRight } from "@tabler/icons-react";

export function FinalCtaSection() {
  return (
    <section className="border-t border-border bg-primary px-5 py-20 text-primary-foreground lg:px-8 h-dvh grid place-content-center ">
      <div className="mx-auto max-w-3xl text-center">
        <div className="mx-auto max-w-xl">
          <SectionHeading
            tone="primary"
            title="Make your next pull request your strongest yet."
            description="Connect your GitHub and let reviewpr bring clarity to every change."
          />
        </div>
        <div className="mt-8 flex justify-center">
          <Button variant="secondary" size="lg" render={<Link to="/login" />}>
            Get started
            <IconArrowRight />
          </Button>
        </div>
      </div>
    </section>
  );
}
