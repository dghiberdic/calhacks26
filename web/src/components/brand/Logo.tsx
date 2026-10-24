/** The mark: a gust that settles into a check. Noise in, one clean line out. */
export function Logo({ className, title }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 48 28" className={className} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      <path d="M2 15 q2.5 -7 5 0 t5 0 t5 0 L23 24 L46 3" fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
