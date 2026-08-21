import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "grid  place-items-center rounded-lg  text-primary-foreground shadow-sm",
        className,
      )}
    >
      {/* <IconShieldCheck className="size-4" strokeWidth={2.4} /> */}

      <span>
        <svg
          className="size-4 fill-foreground  "
          viewBox="0 0 39 45"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path d="M7.8624 21.113C7.9511 20.8693 8.03981 20.6256 8.17286 20.26C10.3017 14.411 16.7915 11.2531 22.7164 13.4096C27.0694 14.994 29.963 19.0831 30.1157 23.5546C30.027 23.7983 29.9826 23.9202 29.8939 24.1639C27.765 30.013 21.2752 33.1708 15.3503 31.0143C10.9974 29.4299 8.18032 25.5067 7.8624 21.113L6.34442e-06 43.091C14.7518 48.4602 31.1133 40.7535 36.5242 25.8871L30.3575 23.6426L38.3408 1.70867C23.589 -3.66055 7.22749 4.04615 1.81658 18.9125L7.8624 21.113Z" />
        </svg>
      </span>
    </span>
  );
}
