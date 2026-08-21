import { Link } from "@tanstack/react-router";
import { IconArrowRight } from "@tabler/icons-react";

import { useSession } from "@/lib/auth";
import { Button } from "@/components/ui/button";

export function AuthCta({ compact = false }: { compact?: boolean }) {
  const { data: session } = useSession();
  const size = compact ? "default" : "lg";

  if (session?.user_id) {
    return (
      <Button size={size} render={<Link to="/dashboard" />}>
        Open dashboard
        <IconArrowRight data-icon="inline-end" className="size-4" />
      </Button>
    );
  }

  return (
    <Button size={size} render={<Link to="/login" />}>
      Sign in
    </Button>
  );
}
