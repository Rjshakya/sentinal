import { createFileRoute, Link } from "@tanstack/react-router";
import { apiBaseUrl } from "../lib/api";
import { useSession } from "../lib/auth";

export const Route = createFileRoute("/about")({ component: Landing });

function Landing() {
  const session = useSession();
  const signedIn = !!session.data;

  return (
    <main className="page-wrap px-4 pb-8 pt-14">
      <section className="island-shell rise-in relative overflow-hidden rounded-[2rem] px-6 py-10 sm:px-10 sm:py-14">
        <div className="pointer-events-none absolute -left-20 -top-24 h-56 w-56 rounded-full bg-[radial-gradient(circle,rgba(79,184,178,0.32),transparent_66%)]" />
        <div className="pointer-events-none absolute -bottom-20 -right-20 h-56 w-56 rounded-full bg-[radial-gradient(circle,rgba(47,106,74,0.18),transparent_66%)]" />
        <p className="island-kicker mb-3">AI Code Review</p>
        <h1 className="display-title mb-5 max-w-3xl text-4xl leading-[1.02] font-bold tracking-tight text-[var(--sea-ink)] sm:text-6xl">
          Reviews that understand the whole codebase.
        </h1>
        <p className="mb-8 max-w-2xl text-base text-[var(--sea-ink-soft)] sm:text-lg">
          Sign in to connect a repository. We index your code, then review every pull request with
          full project context.
        </p>
        <div className="flex flex-wrap gap-3">
          {signedIn ? (
            <Link
              to="/dashboard"
              className="rounded-full border border-[rgba(50,143,151,0.3)] bg-[rgba(79,184,178,0.14)] px-5 py-2.5 text-sm font-semibold text-[var(--lagoon-deep)] no-underline transition hover:-translate-y-0.5 hover:bg-[rgba(79,184,178,0.24)]"
            >
              Open dashboard
            </Link>
          ) : (
            <>
              <a
                href={`${apiBaseUrl}/auth/login?provider=google`}
                className="rounded-full border border-[rgba(50,143,151,0.3)] bg-[rgba(79,184,178,0.14)] px-5 py-2.5 text-sm font-semibold text-[var(--lagoon-deep)] no-underline transition hover:-translate-y-0.5 hover:bg-[rgba(79,184,178,0.24)]"
              >
                Sign in with Google
              </a>
              <a
                href={`${apiBaseUrl}/auth/login?provider=github`}
                className="rounded-full border border-[rgba(23,58,64,0.2)] bg-white/50 px-5 py-2.5 text-sm font-semibold text-[var(--sea-ink)] no-underline transition hover:-translate-y-0.5 hover:border-[rgba(23,58,64,0.35)]"
              >
                Sign in with GitHub
              </a>
            </>
          )}
        </div>
      </section>

      <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[
          [
            "Project-aware",
            "We index your code so reviews understand your codebase, not just the diff.",
          ],
          [
            "Inline feedback",
            "Comments anchored to the exact lines that need attention, with severity tags.",
          ],
          [
            "PR summary",
            "A short verdict at the top of every review so reviewers can triage fast.",
          ],
        ].map(([title, desc]) => (
          <article key={title} className="island-shell feature-card rise-in rounded-2xl p-5">
            <h2 className="mb-2 text-base font-semibold text-[var(--sea-ink)]">{title}</h2>
            <p className="m-0 text-sm text-[var(--sea-ink-soft)]">{desc}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
