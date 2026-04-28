"use client";

import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { Section } from "@/components/primitives/Section";
import { content } from "@/lib/content";
import { fadeUp, fadeUpContainer, viewportOnce } from "@/lib/motion";

export function Connect() {
  const { index, eyebrow, headline, headlineEmphasis, cards } = content.connect;

  return (
    <Section id="connect" index={index} eyebrow={eyebrow}>
      <div className="grid grid-cols-1 gap-y-16 md:grid-cols-12 md:gap-x-12">
        <motion.h2
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          variants={fadeUp}
          className="md:col-span-5 font-serif text-heading font-light leading-[1.05] tracking-tight text-bone"
        >
          {headline}
          <span className="italic text-sage">{headlineEmphasis}</span>
        </motion.h2>

        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          variants={fadeUpContainer(0.08)}
          className="md:col-span-7"
        >
          <div className="grid grid-cols-1 gap-px overflow-hidden bg-bone/10 sm:grid-cols-2">
            {cards.map((card) => (
              <motion.a
                key={card.platform}
                href={card.href}
                target="_blank"
                rel="noreferrer noopener"
                variants={fadeUp}
                className="group relative flex flex-col justify-between gap-8 bg-ink p-8 transition-colors duration-300 hover:bg-[#1A1B19] md:p-10"
              >
                <div className="flex items-start justify-between gap-6">
                  <p className="font-serif text-heading font-light leading-[1.05] tracking-tight text-bone">
                    {card.platform}
                  </p>
                  <ArrowUpRight
                    aria-hidden="true"
                    strokeWidth={1.25}
                    className="h-6 w-6 shrink-0 text-sage transition-transform duration-300 ease-out group-hover:-translate-y-1 group-hover:translate-x-1"
                  />
                </div>

                <p className="text-body text-bone/70">{card.description}</p>

                <p className="font-mono text-caption uppercase tracking-[0.18em] text-bone/40">
                  {card.handle}
                </p>
              </motion.a>
            ))}
          </div>
        </motion.div>
      </div>
    </Section>
  );
}
