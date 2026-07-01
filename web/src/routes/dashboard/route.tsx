import { AppSidebar } from "@/components/app-sidebar";
import ThemeToggle from "@/components/ThemeToggle";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/dashboard")({
  component: DashboardLayout,
});

function DashboardLayout() {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="flex h-16 shrink-0 items-center justify-between gap-2 px-4">
          <SidebarTrigger className="-ml-1" />
          <ThemeToggle />
        </header>
        <Outlet />
      </SidebarInset>
    </SidebarProvider>
  );
}
