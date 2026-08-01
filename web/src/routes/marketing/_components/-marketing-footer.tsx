import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { apiBaseUrl } from "@/lib/api";

export function MarketingFooter() {
  return (
    <footer className="px-5 py-8 lg:px-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2 font-medium text-foreground">
          <BrandMark className="size-6 rounded-md [&_svg]:size-3.5" />
          reviewpr
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" render={<a href="#product" />}>
            Product
          </Button>
          <Button size="sm" variant="ghost" render={<a href="#why" />}>
            Why reviewpr
          </Button>
          <Button
            size="sm"
            variant="ghost"
            render={<a href={`${apiBaseUrl}/auth/login?provider=github`} />}
          >
            Sign in
          </Button>
        </div>
      </div>
      <Separator className="mx-auto mt-6 max-w-6xl" />
      <p className="mx-auto mt-6 max-w-6xl text-xs text-muted-foreground">
        &copy; {new Date().getFullYear()} reviewpr. AI-assisted code review for modern engineering
        teams.
      </p>
    </footer>
  );
}
