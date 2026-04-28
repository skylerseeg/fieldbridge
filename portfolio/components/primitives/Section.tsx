import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type SectionProps = {
  id: string;
  index?: string;
  eyebrow?: string;
  children: ReactNode;
  className?: string;
};

export function Section({
  id,
  index,
  eyebrow,
  children,
  className,
}: SectionProps) {
  return (
    <section
      id={id}
      className={cn(
        "relative w-full px-section-x py-section-y",
        className,
      )}
    >
      <div className="mx-auto w-full max-w-section">
        {(eyebrow || index) && (
          <div className="mb-12 flex items-baseline justify-between font-mono text-caption uppercase tracking-[0.18em] text-bone/40 md:mb-16">
            {eyebrow ? <span>{eyebrow}</span> : <span />}
            {index ? <span>{index}</span> : null}
          </div>
        )}
        {children}
      </div>
    </section>
  );
}
