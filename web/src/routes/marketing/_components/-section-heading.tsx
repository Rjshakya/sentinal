type SectionHeadingProps = {
  eyebrow?: string;
  title: string;
  description?: string;
  align?: "center" | "left";
  tone?: "default" | "primary";
};

export function SectionHeading({
  eyebrow,
  title,
  description,
  align = "center",
  tone = "default",
}: SectionHeadingProps) {
  const centered = align === "center";
  const primary = tone === "primary";

  return (
    <div className={centered ? "text-center" : "text-left"}>
      <div className={centered ? "flex justify-center" : "flex justify-start"}>
        {eyebrow ? (
          <div className={`relative w-fit p-2 ${primary ? "bg-background/10" : "bg-foreground/5"}`}>
            <div className="absolute top-1 left-1 size-0.75 rounded-full bg-foreground/20" />
            <div className="absolute top-1 right-1 size-0.75 rounded-full bg-foreground/20" />
            <div className="absolute bottom-1 left-1 size-0.75 rounded-full bg-foreground/20" />
            <div className="absolute right-1 bottom-1 size-0.75 rounded-full bg-foreground/20" />
            <div
              className={`relative flex h-fit items-center gap-2 rounded-full font-heading px-3 py-1 shadow shadow-black/6.5 dark:border ${
                primary ? "bg-background text-primary" : "bg-background"
              }`}
            >
              <span className="text-sm px-2 ">{eyebrow}</span>
            </div>
          </div>
        ) : null}
      </div>
      <h2
        className={`mt-4 font-heading text-3xl tracking-tight text-balance sm:text-4xl ${
          primary ? "text-primary-foreground" : "text-foreground"
        } ${centered ? "mx-auto" : ""}`}
      >
        {title}
      </h2>
      {description ? (
        <p
          className={`mt-4 max-w-2xl text-sm leading-6 text-balance ${
            primary ? "text-primary-foreground/80" : "text-muted-foreground"
          } ${centered ? "mx-auto" : ""}`}
        >
          {description}
        </p>
      ) : null}
    </div>
  );
}
