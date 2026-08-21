### web/src/routes/dashboard/index.tsx

```diff

index d0dea3a..7542df7 100644
--- a/web/src/routes/dashboard/index.tsx
+++ b/web/src/routes/dashboard/index.tsx
@@ -1,6 +1,5 @@
    2     2  import { ActionsCard } from "@/routes/dashboard/_components/-actions-card";
    3     3  import { GreetingCard } from "@/routes/dashboard/_components/-greeting-card";
    4       -import { IndexedReposCard } from "@/routes/dashboard/_components/-indexed-repos-card";
    5     4  import { StatCard } from "@/routes/dashboard/_components/-stat-card";
    6     5  import { protectPage } from "@/lib/auth";
    7     6  import { useInstallation } from "@/lib/installation";
@@ -43,7 +42,6 @@ function DashboardOverview() {
   44    43            icon={<IconAlertTriangle className="text-muted-foreground size-4" />}
   45    44          />
   46    45        </div>
   47       -      <IndexedReposCard />
   48    46        <ActionsCard />
   49    47        <InstallResultToast />
   50    48      </div>

```
