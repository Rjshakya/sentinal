### web/package.json

```diff

index e254396..ab4749e 100644
--- a/web/package.json
+++ b/web/package.json
@@ -33,13 +33,12 @@
   34    34      "next-themes": "^0.4.6",
   35    35      "react": "^19.2.0",
   36    36      "react-dom": "^19.2.0",
   37       -    "react-syntax-highlighter": "^16.1.1",
   38    37      "shadcn": "^4.12.0",
   39    38      "sonner": "^2.0.7",
   40    39      "tailwind-merge": "^3.6.0",
         40 +    "zustand": "^5.0.2",
   41    41      "tailwindcss": "^4.1.18",
   42       -    "tw-animate-css": "^1.4.0",
   43       -    "zustand": "^5.0.2"
         42 +    "tw-animate-css": "^1.4.0"
   44    43    },
   45    44    "devDependencies": {
   46    45      "@tailwindcss/typography": "^0.5.16",
@@ -50,12 +49,18 @@
   51    50      "@types/node": "^22.10.2",
   52    51      "@types/react": "^19.2.0",
   53    52      "@types/react-dom": "^19.2.0",
   54       -    "@types/react-syntax-highlighter": "^15.5.13",
   55    53      "@vitejs/plugin-react": "^6.0.1",
   56    54      "jsdom": "^28.1.0",
   57    55      "typescript": "^6.0.2",
   58    56      "vite": "^8.0.0",
   59    57      "vitest": "^4.1.5",
   60    58      "wrangler": "^4.70.0"
         59 +  },
         60 +  "pnpm": {
         61 +    "onlyBuiltDependencies": [
         62 +      "esbuild",
         63 +      "lightningcss"
         64 +    ]
   61    65    }
   62    66  }
         67 +

```
