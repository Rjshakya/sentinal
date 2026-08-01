import { useSession } from "@/lib/auth";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

type SessionLike = {
  user_name?: string | null;
  github_login?: string | null;
  email?: string | null;
  profile_picture?: string | null;
};

function displayName(session: SessionLike | undefined): string {
  if (!session) return "there";
  if (session.user_name) return session.user_name;
  if (session.github_login) return session.github_login;
  if (session.email) return session.email.split("@")[0] ?? "there";
  return "there";
}

export function GreetingCard() {
  const { data: session, isLoading } = useSession();
  const name = displayName(session);
  const avatar = session?.profile_picture ?? null;
  const initials = name.charAt(0).toUpperCase();

  return (
    <Card className="bg-background ring-0">
      <CardContent className="flex items-start gap-4 px-0 ">
        {isLoading ? (
          <Skeleton className="size-12 rounded-full" />
        ) : (
          <Avatar size="default" className={"mt-1"}>
            {avatar ? <AvatarImage className={"rounded-md"} src={avatar} alt={name} /> : null}
            <AvatarFallback>{initials}</AvatarFallback>
          </Avatar>
        )}
        <div className="flex flex-col gap-1">
          {isLoading ? (
            <>
              <Skeleton className="h-6 w-48" />
              <Skeleton className="h-4 w-72" />
            </>
          ) : (
            <>
              <h1 className="text-2xl font-semibold tracking-tight font-sans">Hi, {name} </h1>
              <p className="text-muted-foreground text-sm">Here&apos;s your stats.</p>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
