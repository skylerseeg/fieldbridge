"use client";

import { motion } from "framer-motion";
import { Section } from "@/components/primitives/Section";
import { content } from "@/lib/content";
import { fadeUp, fadeUpContainer, viewportOnce } from "@/lib/motion";

export function Building() {
  const { index, eyebrow, headline, headlineEmphasis, projects } =
    content.building;

  return (
    <Section id="building" index={index} eyebrow={eyebrow}>
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

        <motion.ul
          initial="hidden"
          whileInView="visible"
          viewport={viewportOnce}
          variants={fadeUpContainer(0.1)}
          className="md:col-span-7 flex flex-col"
        >
          {projects.map((project) => (
            <motion.li
              key={project.name}
              variants={fadeUp}
              className="grid grid-cols-1 gap-2 border-t border-bone/10 py-8 first:border-t-0 first:pt-0 md:grid-cols-12 md:gap-x-6"
            >
              <div className="md:col-span-4">
                <p className="font-serif text-2xl font-light text-bone">
                  {project.name}
                </p>
                <p className="mt-1 font-mono text-caption uppercase tracking-[0.18em] text-bone/40">
                  {project.role}
                </p>
              </div>
              <p className="md:col-span-6 text-body text-bone/70">
                {project.description}
              </p>
              <p className="md:col-span-2 font-mono text-caption uppercase tracking-[0.18em] text-sage md:text-right">
                {project.status}
              </p>
            </motion.li>
          ))}
        </motion.ul>
      </div>
    </Section>
  );
}
