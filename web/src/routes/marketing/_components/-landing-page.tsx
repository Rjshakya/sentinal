import { FinalCtaSection } from "./-final-cta-section";
import { FeaturesSection } from "./-features-section";
import { HeroSection } from "./-hero-section";
import { MarketingFooter } from "./-marketing-footer";
import { MarketingHeader } from "./-marketing-header";
import { SecuritySection } from "./-security-section";
import { WorkflowSection } from "./-workflow-section";

export function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <MarketingHeader />
      <HeroSection />
      <FeaturesSection />
      <WorkflowSection />
      <SecuritySection />
      <FinalCtaSection />
      <MarketingFooter />
    </div>
  );
}
