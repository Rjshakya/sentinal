import { FeaturesSection } from "./-features-section";
import { FinalCtaSection } from "./-final-cta-section";
import { HeroSection } from "./-hero-section";
import { MarketingFooter } from "./-marketing-footer";
import { MarketingHeader } from "./-marketing-header";
import { WorkflowSection } from "./-workflow-section";

export function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <MarketingHeader />
      <HeroSection />
      <div className="w-full h-44" />
      <FeaturesSection />
      <div className="w-full h-44" />
      <WorkflowSection />
      <div className="w-full h-44" />
      <FinalCtaSection />
      <div className="w-full h-44" />
      <MarketingFooter />
    </div>
  );
}
