import { About } from "@/components/sections/About";
import { Building } from "@/components/sections/Building";
import { Connect } from "@/components/sections/Connect";
import { Hero } from "@/components/sections/Hero";
import { SectionDivider } from "@/components/primitives/SectionDivider";
import { SiteFooter } from "@/components/SiteFooter";

export default function HomePage() {
  return (
    <main className="min-h-screen w-full bg-ink text-bone">
      <Hero />
      <SectionDivider />
      <Building />
      <SectionDivider />
      <Connect />
      <SectionDivider />
      <About />
      <SiteFooter />
    </main>
  );
}
