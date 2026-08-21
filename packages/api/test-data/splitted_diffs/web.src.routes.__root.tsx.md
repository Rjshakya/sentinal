### web/src/routes/__root.tsx

```diff

index ec5f499..3112346 100644
--- a/web/src/routes/__root.tsx
+++ b/web/src/routes/__root.tsx
@@ -6,9 +6,8 @@ import appCss from "../styles.css?url";
    7     7  import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
    8     8  import { Toaster } from "@/components/ui/sonner";
    9     9  import { TooltipProvider } from "@/components/ui/tooltip";
   10       -import { ThemeProvider } from "@/components/theme-provider";
   11    10  
   12       -const THEME_INIT_SCRIPT = `(function(){try{var stored=window.localStorage.getItem('theme');var mode=(stored==='light')?'light':'dark';var root=document.documentElement;root.classList.remove('light','dark');root.classList.add(mode);root.setAttribute('data-theme',mode);root.style.colorScheme=mode;}catch(e){}})();`;
         11 +const THEME_INIT_SCRIPT = `(function(){try{var stored=window.localStorage.getItem('theme');var mode=(stored==='light'||stored==='dark'||stored==='auto')?stored:'auto';var prefersDark=window.matchMedia('(prefers-color-scheme: dark)').matches;var resolved=mode==='auto'?(prefersDark?'dark':'light'):mode;var root=document.documentElement;root.classList.remove('light','dark');root.classList.add(resolved);if(mode==='auto'){root.removeAttribute('data-theme')}else{root.setAttribute('data-theme',mode)}root.style.colorScheme=resolved;}catch(e){}})();`;
   13    12  
   14    13  export const Route = createRootRoute({
   15    14    head: () => ({
@@ -83,10 +82,8 @@ function RootDocument({ children }: { children: React.ReactNode }) {
   84    83        </head>
   85    84        <body className="">
   86    85          <QueryClientProvider client={queryClient}>
   87       -          <ThemeProvider>
   88       -            <TooltipProvider>{children}</TooltipProvider>
   89       -            <Toaster />
   90       -          </ThemeProvider>
         86 +          <TooltipProvider>{children}</TooltipProvider>
         87 +          <Toaster />
   91    88          </QueryClientProvider>
   92    89          <TanStackDevtools
   93    90            config={{

```
