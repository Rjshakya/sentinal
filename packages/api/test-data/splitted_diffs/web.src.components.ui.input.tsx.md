### web/src/components/ui/input.tsx

```diff

index 91a3eb6..ef33fc5 100644
--- a/web/src/components/ui/input.tsx
+++ b/web/src/components/ui/input.tsx
@@ -1,7 +1,7 @@
    2       -import * as React from "react";
    3       -import { Input as InputPrimitive } from "@base-ui/react/input";
          2 +import * as React from "react"
          3 +import { Input as InputPrimitive } from "@base-ui/react/input"
    4     4  
    5       -import { cn } from "@/lib/utils";
          5 +import { cn } from "@/lib/utils"
    6     6  
    7     7  function Input({ className, type, ...props }: React.ComponentProps<"input">) {
    8     8    return (
@@ -10,11 +10,11 @@ function Input({ className, type, ...props }: React.ComponentProps<"input">) {
   11    11        data-slot="input"
   12    12        className={cn(
   13    13          "h-8 w-full min-w-0 rounded-none border border-input bg-transparent px-2.5 py-1 text-xs transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-xs file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-1 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-1 aria-invalid:ring-destructive/20 md:text-xs dark:bg-input/30 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
   14       -        className,
         14 +        className
   15    15        )}
   16    16        {...props}
   17    17      />
   18       -  );
         18 +  )
   19    19  }
   20    20  
   21       -export { Input };
         21 +export { Input }

```
