import { HeadContent, Scripts, createRootRoute } from "@tanstack/react-router";
import { TanStackRouterDevtoolsPanel } from "@tanstack/react-router-devtools";
import { TanStackDevtools } from "@tanstack/react-devtools";

import appCss from "../styles.css?url";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

const THEME_INIT_SCRIPT = `(function(){try{var stored=window.localStorage.getItem('theme');var mode=(stored==='light'||stored==='dark'||stored==='auto')?stored:'auto';var prefersDark=window.matchMedia('(prefers-color-scheme: dark)').matches;var resolved=mode==='auto'?(prefersDark?'dark':'light'):mode;var root=document.documentElement;root.classList.remove('light','dark');root.classList.add(resolved);if(mode==='auto'){root.removeAttribute('data-theme')}else{root.setAttribute('data-theme',mode)}root.style.colorScheme=resolved;}catch(e){}})();`;

export const Route = createRootRoute({
  head: () => ({
    meta: [
      {
        charSet: "utf-8",
      },
      { title: "ReviewPR — AI code reviewer" },
      {
        name: "description",
        content: "AI-powered PR reviews , Catch bugs before you regret",
      },

      // Open Graph
      { property: "og:type", content: "website" },
      { property: "og:site_name", content: "ReviewPR" },
      {
        property: "og:title",
        content: "ReviewPR — AI code reviewer",
      },
      {
        property: "og:description",
        content: "AI-powered PR reviews , Catch bugs before you regret",
      },
      { property: "og:image", content: "https://reviewpr.app/reviewpr-og.png" },
      { property: "og:image:width", content: "1200" },
      { property: "og:image:height", content: "630" },
      { property: "og:url", content: "https://reviewpr.app" },

      // Twitter
      { name: "twitter:card", content: "summary_large_image" },
      {
        name: "twitter:title",
        content: "ReviewPR — AI code reviewer",
      },
      {
        name: "twitter:description",
        content: "AI-powered PR reviews , Catch bugs before you regret",
      },
      { name: "twitter:image", content: "https://reviewpr.app/reviewpr-og.png" },
      // { name: "twitter:site", content: "@reviewpr" }, // add once you have a handle

      // Robots / theme
      { name: "robots", content: "index, follow" },
      { name: "theme-color", content: "#0a0a0a" },
    ],
    links: [
      {
        rel: "stylesheet",
        href: appCss,
      },
      {
        rel: "icon",
        type: "image/png",
        href: "/reviewpr-icon.png",
      },
      { rel: "canonical", href: "https://reviewpr.app" },
    ],
  }),
  shellComponent: RootDocument,
});

const queryClient = new QueryClient();

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <HeadContent />
      </head>
      <body className="">
        <QueryClientProvider client={queryClient}>
          <TooltipProvider>{children}</TooltipProvider>
          <Toaster />
        </QueryClientProvider>
        <TanStackDevtools
          config={{
            position: "bottom-right",
          }}
          plugins={[
            {
              name: "Tanstack Router",
              render: <TanStackRouterDevtoolsPanel />,
            },
          ]}
        />
        <Scripts />
      </body>
    </html>
  );
}
