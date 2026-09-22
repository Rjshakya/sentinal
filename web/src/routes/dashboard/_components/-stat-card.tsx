import type { ReactNode } from "react";

import { CommonCard } from "@/components/common-card";
import { CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

type StatCardProps = {
  label: string;
  value: number | undefined;
  loading: boolean;
  icon: ReactNode;
};

export function StatCard({ label, value, loading, icon }: StatCardProps) {
  return (
    <CommonCard
      headerClassName="flex flex-row items-center justify-between gap-2 space-y-0"
      header={
        <>
          <CardTitle>{label}</CardTitle>
          {icon}
        </>
      }
      body={
        loading || value === undefined ? (
          <Skeleton className="h-8 w-16" />
        ) : (
          <div className="text-3xl font-semibold tracking-tight">{value.toLocaleString()}</div>
        )
      }
    />
  );
}
