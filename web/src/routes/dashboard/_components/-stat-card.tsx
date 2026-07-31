import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

type StatCardProps = {
  label: string;
  value: number | undefined;
  loading: boolean;
  icon: ReactNode;
};

export function StatCard({ label, value, loading, icon }: StatCardProps) {
  return (
    <div className="p-1 ring-1 ring-foreground/10 grid gap-2">
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle>{label}</CardTitle>
        {icon}
      </CardHeader>
      <Card className=" bg-accent  dark:bg-card">
        <CardContent>
          {loading || value === undefined ? (
            <Skeleton className="h-8 w-16" />
          ) : (
            <div className="text-3xl font-semibold tracking-tight">{value.toLocaleString()}</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
