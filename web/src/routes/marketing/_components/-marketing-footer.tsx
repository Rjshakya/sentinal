import { FooterText } from "./-footer-text";

export function MarketingFooter() {
  return (
    <footer className="">
      <div className="mx-auto w-full max-w-[1440px] px-4 pt-10 pb-8 sm:px-6 md:px-8">
        <div className="w-full [&_svg]:block [&_svg]:h-auto [&_svg]:w-full">
          <FooterText />
        </div>
      </div>
    </footer>
  );
}
