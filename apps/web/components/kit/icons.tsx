// The console's line icons (design-review/DESIGN_SYSTEM.md §3): a 24-unit grid, 1.75 stroke, drawn in the text's colour.
// Always beside a word or inside a control that has an accessible name; the icon itself is hidden from assistive tech.

const PATHS = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  fileplus: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M14 3v5h5 M12 12v6 M9 15h6",
  plus: "M12 5v14 M5 12h14",
  doc: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M14 3v5h5 M9 13h6 M9 17h6",
  box: "M3 7.5 12 3l9 4.5-9 4.5z M3 7.5V17l9 4.5 9-4.5V7.5 M12 12v9.5",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 7v5l3 2",
  shield: "M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z M9 12l2 2 4-4",
  building: "M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16 M16 9h2a2 2 0 0 1 2 2v10 M2 21h20 M8 7h4 M8 11h4 M8 15h4",
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M22 21v-2a4 4 0 0 0-3-3.9 M16 3.1a4 4 0 0 1 0 7.8",
  chart: "M4 20V4 M4 20h16 M8 16l4-5 3 3 5-7",
  cpu: "M9 3v2 M15 3v2 M9 19v2 M15 19v2 M3 9h2 M3 15h2 M19 9h2 M19 15h2 M7 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z M9 9h6v6H9z",
  key: "M15 7a4 4 0 1 1-3.9 4.9L3 20v-3l2-2v-2h2l1.9-1.9A4 4 0 0 1 15 7z M16 8h.01",
  gauge: "M12 15l4-4 M3.5 17a9 9 0 1 1 17 0",
  pipeline: "M4 6h6 M14 6h6 M4 18h6 M14 18h6 M10 6a2 2 0 1 0 4 0 2 2 0 0 0-4 0 M10 18a2 2 0 1 0 4 0 2 2 0 0 0-4 0 M12 8v8",
  checkc: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M8 12.5l3 3 5-6",
  alert: "M12 3 2 20h20z M12 10v4 M12 17h.01",
  dotc: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  half: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 3v18",
  lock: "M6 11h12v10H6z M8 11V7a4 4 0 1 1 8 0v4",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 11v5 M12 8h.01",
  xc: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M9 9l6 6 M15 9l-6 6",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z M21 21l-4.3-4.3",
  chevl: "M15 6l-6 6 6 6", chevr: "M9 6l6 6-6 6", chevd: "M6 9l6 6 6-6",
  menu: "M4 6h16 M4 12h16 M4 18h16", x: "M6 6l12 12 M18 6 6 18",
  bell: "M6 16v-5a6 6 0 1 1 12 0v5l1.5 2h-15z M10 21h4",   // notifications (the Graphite page bar, R2)
  sliders: "M4 6h9 M17 6h3 M4 12h3 M11 12h9 M4 18h11 M19 18h1 M15 4v4 M9 10v4 M17 16v4",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg className={`ico${className ? ` ${className}` : ""}`} viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
         strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      <path d={PATHS[name]} />
    </svg>
  );
}
