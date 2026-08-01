import { IconLayoutDashboard, IconFolders, IconClipboardCheck, IconSettings } from "@tabler/icons-react";
import type { ReactNode } from "react";

export type NavItem = {
  title: string;
  url: string;
  icon: ReactNode;
};

export const navItems: NavItem[] = [
  { title: "Overview",      url: "/dashboard",            icon: <IconLayoutDashboard className="size-4" /> },
  { title: "Repositories",  url: "/dashboard/repositories", icon: <IconFolders className="size-4" /> },
  { title: "Reviews",       url: "/dashboard/reviews",      icon: <IconClipboardCheck className="size-4" /> },
  { title: "Settings",      url: "/dashboard/settings",     icon: <IconSettings className="size-4" /> },
];
