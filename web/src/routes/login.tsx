import { Link, createFileRoute, redirect } from "@tanstack/react-router";

import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiBaseUrl, apiClient, type Session } from "@/lib/api";

export const Route = createFileRoute("/login")({
  component: LoginPage,
  ssr: false,
  beforeLoad: async () => {
    let session: Session | null = null;
    try {
      session = await apiClient.session();
    } catch (error) {
      if (error instanceof ApiError) return;
      throw error;
    }
    if (session?.user_id) {
      throw redirect({ to: "/dashboard" });
    }
  },
});

function LoginPage() {
  return (
    <main className="bg-background">
      <div className="flex min-h-dvh items-center justify-center p-6">
        <Card className="w-full max-w-72 text-center bg-background ring-0 gap-2 ">
          <CardHeader className=" items-start text-start gap-10 mb-2 ">
            <Link to="/" aria-label="Go home" className="w-full flex  items-start  ">
              <BrandMark className="border bg-primary   p-3 " />
            </Link>
            <div className="space-y-1">
              <CardTitle className=" text-sm tracking-tighter  ">Sign in</CardTitle>
              <CardDescription className="text-xs ">Please sign in to continue</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {/*<Button
              size="lg"
              className="w-full"
              render={<a href={`${apiBaseUrl}/auth/login?provider=github`} />}
            >
              <IconBrandGithub />
              Sign in with GitHub
            </Button> */}
            <Button
              size="lg"
              variant="outline"
              className="w-full"
              render={<a href={`${apiBaseUrl}/auth/login?provider=google`} />}
            >
              Google
            </Button>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
