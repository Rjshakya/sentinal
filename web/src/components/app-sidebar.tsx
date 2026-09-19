"use client";

import * as React from "react";
import { Component, type ReactNode } from "react";
import { NavMain } from "@/components/nav-main";
import { NavUser } from "@/components/nav-user";
import { PullFilesTree } from "@/components/pull-files-tree";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { navItems } from "@/lib/nav";
import { BrandMark } from "./brand-mark";
import { useParams } from "@tanstack/react-router";

function usePullParams(): { owner: string; repo: string; number: number } | null {
  const params = useParams({ strict: false });
  const owner = (params as Record<string, unknown>).owner;
  const repo = (params as Record<string, unknown>).repo;
  const number = (params as Record<string, unknown>).number;
  if (typeof owner !== "string" || typeof repo !== "string" || typeof number !== "string") {
    return null;
  }
  const prNumber = Number(number);
  if (!Number.isInteger(prNumber) || prNumber < 1) return null;
  return { owner, repo, number: prNumber };
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  return (
    <Sidebar variant="inset" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<a href="/dashboard" />}>
              <BrandMark className="p-3 bg-background " />
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">AI Code Review</span>
                <span className="truncate text-xs">Dashboard</span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={navItems} />
        <PullFilesGroup />
      </SidebarContent>
      <SidebarFooter>
        <NavUser />
      </SidebarFooter>
    </Sidebar>
  );
}

class TreeErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  render(): ReactNode {
    if (this.state.failed) {
      return (
        <p className="text-muted-foreground px-2 text-xs">
          Failed to load files.
        </p>
      );
    }
    return this.props.children;
  }
}

function PullFilesGroup() {
  const pull = usePullParams();
  if (!pull) return null;
  return (
    <SidebarGroup>
      <SidebarGroupLabel className="">Files</SidebarGroupLabel>
      <SidebarGroupContent className="">
        <TreeErrorBoundary>
          <PullFilesTree
            key={`${pull.owner}/${pull.repo}/${pull.number}`}
            owner={pull.owner}
            repo={pull.repo}
            number={pull.number}
          />
        </TreeErrorBoundary>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}
