
export function FinalCtaSection() {
  return (
    <section className="bg-black text-white">
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 md:px-8 md:py-24">
        <div className="relative  flex min-h-[520px] w-full max-w-2xl mx-auto flex-col justify-center items-center">
          <h2 className="relative text-h1 text-white w-fit ">
            You{" "}
            <span className="relative inline-block">
              <span className="relative z-10 mix-blend-exclusion">Ship</span>
              <img
                src="/cta-2.png"
                alt=""
                aria-hidden="true"
                className="pointer-events-none absolute -top-[1.1em] left-[5%] z-0 aspect-square w-[4em] object-cover"
              />
            </span>{" "}
            Code
            <br />
            We{" "}
            <span className="relative inline-block">
              <span className="relative z-10 mix-blend-exclusion">Catch</span>
              <img
                src="/cta.png"
                alt=""
                aria-hidden="true"
                className="pointer-events-none absolute -right-[0.4em] -bottom-[1.5em] z-0 aspect-square w-[3em] object-cover"
              />
            </span>{" "}
            <span className="relative z-10 mix-blend-exclusion">Bugs</span>
          </h2>
        </div>
      </div>
    </section>
  );
}
