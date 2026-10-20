import { Link } from "@tanstack/react-router";

import { Button } from "@/components/ui/button";

import { HeroReviewCard } from "./-hero-review-card";
import { BrandMark } from "@/components/brand-mark";

export function HeroSection() {
  return (
    <section id="home" className="overflow-x-clip bg-black text-white pt-28">
      {/* Copy */}
      <div className="mx-auto w-full max-w-6xl px-4 pt-12 pb-14 sm:px-6 md:px-8 md:pt-20 md:pb-20 ">
        <div className="max-w-2xl mx-auto w-full  text-left">
          <h2 className="text-white">
            Open - Source
            <br />
            Code Reviewer
          </h2>
          <p className="mt-5 pl-1 max-w-md text-sm leading-6 text-balance text-white/70">
            An AI reviewer that reads your whole repo, not just the diff. Catches bugs before they
            hit production.
          </p>
          <div className="mt-10">
            <Button size="lg" className="rounded-full text-lg py-6 px-8" render={<Link to="/login" />}>
              Get Started
            </Button>
          </div>
        </div>
      </div>

      {/* Visual */}
      <div className="mt-32 w-full px-3 md:mt-28 md:px-6">
        <div className="relative h-[430px] md:h-[750px] w-full overflow-hidden bg-[url(/hero-bg.png)] bg-cover bg-center bg-no-repeat p-0 md:px-8 md:py-16">
          <div className="absolute md:top-50 top-20 right-0 bottom-0 md:left-80 left-20 w-full h-full ">
            <BrandMark className="hidden shrink-0 drop-shadow-2xl h-full " />
            <div className="w-full h-full md:scale-110 scale-105 ">
              <HeroReviewCard />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
