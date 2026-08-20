### web/src/routes/login.tsx

```diff

index f0d81ee..61d720c 100644
--- a/web/src/routes/login.tsx
+++ b/web/src/routes/login.tsx
@@ -1,15 +1,16 @@
    2     2  import { Link, createFileRoute, redirect } from "@tanstack/react-router";
          3 +import { IconBrandGithub, IconBrandGoogle } from "@tabler/icons-react";
    3     4  
    4     5  import { BrandMark } from "@/components/brand-mark";
    5     6  import { Button } from "@/components/ui/button";
    6     7  import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
    7       -import { ApiError, apiBaseUrl, apiClient, type Session } from "@/lib/api";
          8 +import { ApiError, apiBaseUrl, apiClient } from "@/lib/api";
    8     9  
    9    10  export const Route = createFileRoute("/login")({
   10    11    component: LoginPage,
   11    12    ssr: false,
   12    13    beforeLoad: async () => {
   13       -    let session: Session | null = null;
         14 +    let session: Awaited<ReturnType<typeof apiClient.session>> | null = null;
   14    15      try {
   15    16        session = await apiClient.session();
   16    17      } catch (error) {

```
