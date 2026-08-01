import { Link } from "@tanstack/react-router";
import {
  IconAlertTriangle,
  IconCircleCheck,
  IconClipboardCheck,
  IconCommand,
  IconFolders,
  IconLayoutDashboard,
  IconMenu2,
  IconMessage2,
  IconSelector,
  IconSettings,
} from "@tabler/icons-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const NAV_ITEMS = [
  { title: "Overview", icon: <IconLayoutDashboard className="size-4" />, active: true },
  { title: "Repositories", icon: <IconFolders className="size-4" /> },
  { title: "Reviews", icon: <IconClipboardCheck className="size-4" /> },
  { title: "Settings", icon: <IconSettings className="size-4" /> },
];

const STATS = [
  {
    label: "PRs reviewed",
    value: "1,234",
    icon: <IconClipboardCheck className="text-muted-foreground size-4" />,
  },
  {
    label: "Comments issued",
    value: "562",
    icon: <IconMessage2 className="text-muted-foreground size-4" />,
  },
  {
    label: "Bugs caught",
    value: "89",
    icon: <IconAlertTriangle className="text-muted-foreground size-4" />,
  },
];

function DashboardPreview() {
  return (
    <div className=" overflow-hidden border  bg-background  dark:bg-background scale-95  md:scale-90  ">
      <div className="grid origin-top-left lg:grid-cols-[auto_1fr]  ">
        {/* Sidebar */}
        <div className="hidden w-64 grid-rows-[auto_1fr_auto] p-4 lg:grid bg-sidebar ">
          {/* Brand */}
          <div className="flex cursor-pointer items-center gap-2 rounded-lg p-2 hover:bg-foreground/5">
            <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <IconCommand className="size-4" />
            </div>
            <div className="grid flex-1 text-left text-sm leading-tight">
              <span className="truncate font-medium">AI Code Review</span>
              <span className="truncate text-xs text-muted-foreground">Dashboard</span>
            </div>
          </div>

          {/* Nav */}
          <div className="mt-6 flex flex-col gap-1">
            {NAV_ITEMS.map((item) => (
              <div
                key={item.title}
                className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium ${
                  item.active
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-foreground/3"
                }`}
              >
                {item.icon}
                {item.title}
              </div>
            ))}
          </div>

          {/* User */}
          <div className="flex cursor-pointer items-center gap-2 rounded-lg p-2 hover:bg-foreground/5">
            <div className="flex size-8 bg-pink-600 items-center justify-center rounded-md   text-xs text-white  font-medium">
              A
            </div>
            <div className="grid flex-1 text-left text-sm leading-tight">
              <span className="truncate  font-medium">Alex Rivera</span>
              <span className="truncate text-xs text-muted-foreground">alex@acme.dev</span>
            </div>
            <IconSelector className="ml-auto size-4 opacity-60" />
          </div>
        </div>

        {/* Main Content */}
        <div className="bg-background">
          <div className=" shadow ring-1 ring-border lg:rounded-xl">
            {/* Topbar */}
            <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b px-1">
              <div className="flex size-8 cursor-pointer items-center justify-center rounded-md hover:bg-foreground/5">
                <IconMenu2 className="size-4" />
              </div>
              <div className="flex cursor-pointer items-center rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-foreground/5">
                Auto
              </div>
            </div>

            <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-4 pt-6">
              {/* Greeting */}
              <Card className="bg-background  ring-0">
                <CardContent className="flex items-start gap-4 ">
                  <Avatar className="mt-1 rounded-md border-none">
                    <AvatarFallback className={"rounded-md bg-pink-600 text-white"}>
                      A
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex flex-col gap-1">
                    <h1 className="font-sans text-2xl font-semibold tracking-tight">Hi, Alex</h1>
                    <p className="text-muted-foreground text-sm">Here&apos;s your stats.</p>
                  </div>
                </CardContent>
              </Card>

              {/* Stats */}
              <div className="grid gap-2 md:grid-cols-3">
                {STATS.map((stat) => (
                  <div key={stat.label} className="grid gap-2 p-1 ring-1 ring-foreground/10">
                    <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
                      <CardTitle>{stat.label}</CardTitle>
                      {stat.icon}
                    </CardHeader>
                    <Card className="bg-accent dark:bg-card">
                      <CardContent>
                        <div className="text-3xl font-semibold tracking-tight">{stat.value}</div>
                      </CardContent>
                    </Card>
                  </div>
                ))}
              </div>

              {/* Actions */}
              <div className="flex flex-col gap-4">
                <CardTitle className="">Actions</CardTitle>
                <div className="grid gap-2 p-1.5 ring-1 ring-foreground/10">
                  <CardHeader>
                    <div className="flex items-center justify-between gap-2">
                      <CardTitle>Github</CardTitle>
                      <Badge variant="ghost" className="text-green-600">
                        <IconCircleCheck />
                        connected
                      </Badge>
                    </div>
                  </CardHeader>
                  <Card className="bg-accent dark:bg-card">
                    <CardContent className="grid gap-4">
                      <CardDescription>
                        You&apos;re connected. Pick the repositories Sentinel should review.
                      </CardDescription>
                    </CardContent>
                    <CardFooter>
                      <Button variant="default">
                        <IconFolders />
                        Configure repositories
                      </Button>
                    </CardFooter>
                  </Card>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function HeroSection() {
  return (
    <section id="home" className="overflow-x-hidden pb-6">
      {/* Hero Content */}
      <div className="relative mx-auto max-w-6xl border-x border-b px-3 pt-24 pb-10  md:pb-20">
        {/* Announcement Badge */}
        <div className="flex justify-center">
          <div className="relative mx-auto w-fit bg-foreground/5 p-2">
            <div className="absolute top-1 left-1 size-0.75 rounded-full bg-foreground/20" />
            <div className="absolute top-1 right-1 size-0.75 rounded-full bg-foreground/20" />
            <div className="absolute bottom-1 left-1 size-0.75 rounded-full bg-foreground/20" />
            <div className="absolute right-1 bottom-1 size-0.75 rounded-full bg-foreground/20" />
            <div className="relative flex h-fit items-center gap-2 rounded-full bg-background font-heading  px-3 py-1 shadow shadow-black/6.5 dark:border">
              <span className="text-title text-sm px-2 ">
                AI - powered code review agent
                {/* <span className="text-primary ml-1">Learn more</span>{" "} */}
              </span>
            </div>
          </div>
        </div>

        {/* Hero Text */}
        <div className="mx-auto mt-8 max-w-3xl text-center ">
          <h1 className="text-4xl font-heading tracking-tighter  text-balance text-foreground sm:text-5xl lg:text-6xl">
            Ship with confidence. <span className="">Review smarter.</span>
          </h1>
          <p className=" mx-auto mt-4 mb-8 max-w-lg text-xs  text-balance text-muted-foreground">
            Code reviewer agent that helps you ship quality code to production. Catch bugs, security
            issues, and style problems before they reach your users.
          </p>
          <div className="flex items-center justify-center gap-4 mt-8 ">
            <Button size="lg" render={<Link to="/login" />}>
              Get Started
            </Button>
            <Button size="lg" variant="outline" className="" render={<a href="#how-it-works" />}>
              How it works
            </Button>
          </div>
        </div>
      </div>

      {/* Dashboard Preview */}
      <div className="border-b ">
        <div className="relative mx-auto max-w-6xl border-x px-4 sm:px-6 md:px-12">
          {/* Corner decorations */}
          <div className="pointer-events-none absolute z-10 size-1.5 border border-transparent bg-card shadow-sm ring-1 ring-foreground/10 top-[-3.5px] left-[-3.5px]" />
          <div className="pointer-events-none absolute z-10 size-1.5 border border-transparent bg-card shadow-sm ring-1 ring-foreground/10 top-[-3.5px] left-3 translate-x-[1.5px] sm:left-5 md:left-11" />
          <div className="pointer-events-none absolute z-10 size-1.5 border border-transparent bg-card shadow-sm ring-1 ring-foreground/10 top-[-3.5px] right-[-3.5px]" />
          <div className="pointer-events-none absolute z-10 size-1.5 border border-transparent bg-card shadow-sm ring-1 ring-foreground/10 top-[-3.5px] right-3 translate-x-[-1.5px] sm:right-5 md:right-11" />
          <div className="pointer-events-none absolute z-10 size-1.5 border border-transparent bg-card shadow-sm ring-1 ring-foreground/10 bottom-[-3.5px] left-[-3.5px]" />
          <div className="pointer-events-none absolute z-10 size-1.5 border border-transparent bg-card shadow-sm ring-1 ring-foreground/10 bottom-[-3.5px] left-3 translate-x-[1.5px] sm:left-5 md:left-11" />
          <div className="pointer-events-none absolute z-10 size-1.5 border border-transparent bg-card shadow-sm ring-1 ring-foreground/10 right-[-3.5px] bottom-[-3.5px]" />
          <div className="pointer-events-none absolute z-10 size-1.5 border border-transparent bg-card shadow-sm ring-1 ring-foreground/10 right-3 bottom-[-3.5px] translate-x-[-1.5px] sm:right-5 md:right-11" />

          <div className="border-x px-0  md:p-8  bg-[url(/reviewpr-hero.png)] bg-no-repeat bg-cover  ">
            <DashboardPreview />
          </div>
        </div>
      </div>
    </section>
  );
}
