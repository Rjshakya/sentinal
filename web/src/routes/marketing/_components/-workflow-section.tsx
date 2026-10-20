import { HTW1 } from "./-htw-1";
import { HTW2 } from "./-htw-2";

const steps = [
  {
    title: "Clone your repo",
    art: (
      <div className="h-full w-full [&_svg]:block [&_svg]:h-full [&_svg]:w-full [&_svg]:object-cover">
        <HTW1 />
      </div>
    ),
  },
  {
    title: "Parallel agents review",
    art: (
      <div className="h-full w-full [&_svg]:block [&_svg]:h-full [&_svg]:w-full [&_svg]:object-cover">
        <HTW2 />
      </div>
    ),
  },
  {
    title: "Agents post to GitHub",
    art: (
      <img
        src="/htw-3-img.png"
        alt="Review comments posted to GitHub"
        loading="lazy"
        decoding="async"
        className="block h-auto w-full object-cover"
      />
    ),
  },
];

export function WorkflowSection() {
  return (
    <section id="how-it-works" className=" max-w-2xl mx-auto ">
      <div className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6 md:px-8 md:py-20">
        <h2 className="text-white">How it works?</h2>
        <div className="mx-auto mt-8 flex w-full max-w-2xl flex-col gap-8 md:mt-10">
          {steps.map((step, i) => (
            <figure
              key={step.title}
              className={`overflow-hidden bg-white p-2 grid gap-2 ${i === 2 ? "[contain-intrinsic-size:500px] [content-visibility:auto]" : ""}`}
            >
              <div className=" w-full overflow-hidden bg-black">{step.art}</div>
              <figcaption className="">
                <h3 className="text-black">{step.title}</h3>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
