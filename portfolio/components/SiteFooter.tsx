export function SiteFooter() {
  return (
    <footer className="w-full border-t border-bone/10 px-section-x py-12">
      <div className="mx-auto grid w-full max-w-section grid-cols-1 gap-4 font-mono text-caption uppercase tracking-[0.18em] text-bone/40 md:grid-cols-3 md:items-center">
        <p className="md:text-left">© 2026 Skyler Seegmiller</p>
        <p className="md:text-center">Salt Lake City, Utah</p>
        <p className="md:text-right">
          <a
            href="mailto:hello@skylerseegmiller.com"
            className="transition-colors duration-200 hover:text-sage"
          >
            hello@skylerseegmiller.com
          </a>
        </p>
      </div>
    </footer>
  );
}
