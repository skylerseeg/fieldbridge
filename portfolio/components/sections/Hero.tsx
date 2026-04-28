"use client";

import { motion } from "framer-motion";
import { content } from "@/lib/content";
import { fadeUp, fadeUpContainer } from "@/lib/motion";

export function Hero() {
  const { name, headline, headlineEmphasis, subhead, location } = content.hero;

  return (
    <section
      id="hero"
      className="relative flex min-h-[100svh] w-full flex-col justify-between px-section-x pb-section-y pt-section-y"
    >
      <motion.div
        initial="hidden"
        animate="visible"
        variants={fadeUpContainer(0.12)}
        className="mx-auto flex w-full max-w-section flex-1 flex-col justify-between gap-24"
      >
        <motion.div
          variants={fadeUp}
          className="flex items-baseline justify-between font-mono text-caption uppercase tracking-[0.18em] text-bone/40"
        >
          <span>{name}</span>
          <span>{location}</span>
        </motion.div>

        <motion.h1
          variants={fadeUp}
          className="font-serif text-display font-light leading-[0.95] tracking-tight text-bone"
        >
          {headline}
          <br />
          <span className="italic text-sage">{headlineEmphasis}</span>
        </motion.h1>

        <motion.p
          variants={fadeUp}
          className="max-w-xl font-sans text-body text-bone/70"
        >
          {subhead}
        </motion.p>
      </motion.div>
    </section>
  );
}
