import { Feat1 } from "./-feat-1";
import { Feat2 } from "./-feat-2";
import { Feat3 } from "./-feat-3";

const features = [
  { title: "Context of your repo", art: <Feat1 className="h-full w-full [&_svg]:block [&_svg]:h-full [&_svg]:w-full [&_svg]:object-cover" /> },
  { title: "Configure as per your need", art: <Feat2 className="h-full w-full [&_svg]:block [&_svg]:h-full [&_svg]:w-full [&_svg]:object-cover" /> },
  { title: "Comments where you fix them", art: <Feat3 className="h-full w-full [&_svg]:block [&_svg]:h-full [&_svg]:w-full [&_svg]:object-cover" /> },
];

export function FeaturesSection() {
  return (
    <section id="product" className=" max-w-2xl mx-auto ">
      <div className="mx-auto w-full max-w-6xl px-4 py-14 sm:px-6  md:py-20">
        <h2 className="text-white w-full ">Features</h2>
        <div className="mx-auto mt-8 flex w-full max-w-2xl flex-col gap-8 md:mt-10">
          {features.map((feature) => (
            <figure
              key={feature.title}
              className="overflow-hidden bg-white p-2 grid gap-2 "
            >
              <div className=" w-full overflow-hidden bg-black">
                {feature.art}
              </div>
              <figcaption className="">
                <h3 className="text-black">{feature.title}</h3>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
