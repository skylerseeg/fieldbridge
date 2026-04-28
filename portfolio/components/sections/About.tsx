"use client";

import { motion } from "framer-motion";
import { Section } from "@/components/primitives/Section";
import { content } from "@/lib/content";
import { fadeUp, fadeUpContainer, viewportOnce } from "@/lib/motion";
import { cn } from "@/lib/cn";

export function About() {
  const { index, eyebrow, headline, headlineEmphasis, paragraphs } =
    content.about;

  return (
    <Section id="about" index={index} eyebrow={eyebrow}>
      <div className="max-w-3xl">
        <motion.h2
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          variants={fadeUp}
          className="font-serif text-heading font-light leading-[1.05] tracking-tight text-bone"
        >
          {headline}
          <span className="italic text-sage">{headlineEmphasis}</span>
        </motion.h2>

        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          variants={fadeUpContainer(0.15)}
          className="mt-16"
        >
          {paragraphs.map((paragraph, i) => (
            <motion.p
              key={i}
              variants={fadeUp}
              className={cn(
                "font-serif text-heading font-light leading-[1.15] tracking-tight",
                i === 0 ? "mt-0" : "mt-8 md:mt-10",
                paragraph.muted ? "text-bone/60" : "text-bone",
                paragraph.italic ? "italic" : "",
              )}
            >
              {paragraph.text}
            </motion.p>
          ))}
        </motion.div>
      </div>
    </Section>
  );
}
