import { Link, createFileRoute, redirect } from "@tanstack/react-router";
import { IconBrandGithub, IconBrandGoogle } from "@tabler/icons-react";

import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, apiBaseUrl, apiClient } from "@/lib/api";

export const Route = createFileRoute("/login")({
  component: LoginPage,
  ssr: false,
  beforeLoad: async () => {
    let session: Awaited<ReturnType<typeof apiClient.session>> | null = null;
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
        <Card className="w-full max-w-72 text-center bg-background ring-0 ">
          <CardHeader className="items-center text-center mb-8 ">
            <Link
              to="/"
              aria-label="Go home"
              className="mx-auto flex size-10 items-center justify-center"
            >
              <BrandMark className="" />
            </Link>
            <div className="space-y-2">
              <CardTitle className="text-xl">Sign in</CardTitle>
              <CardDescription className="text-sm">Please sign in to your account</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Button
              size="lg"
              className="w-full"
              render={<a href={`${apiBaseUrl}/auth/login?provider=github`} />}
            >
              <IconBrandGithub />
              Sign in with GitHub
            </Button>
            <Button
              size="lg"
              variant="outline"
              className="w-full"
              render={<a href={`${apiBaseUrl}/auth/login?provider=google`} />}
            >
              <IconBrandGoogle />
              Sign in with Google
            </Button>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
