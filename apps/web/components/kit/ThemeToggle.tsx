"use client";

import { useEffect, useState } from "react";

// The viewer's choice: follow the system, or always light, or always dark. Kept in this browser only; the inline
// script in the root layout applies it before the first paint, so a page never flashes the other theme.
export const THEME_KEY = "modeler-theme";
type Choice = "system" | "light" | "dark";
const CHOICES: { id: Choice; label: string }[] = [
  { id: "system", label: "Auto" }, { id: "light", label: "Light" }, { id: "dark", label: "Dark" },
];

function apply(choice: Choice) {
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
}

export function ThemeToggle() {
  const [choice, setChoice] = useState<Choice>("system");
  useEffect(() => {
    try {
      const saved = localStorage.getItem(THEME_KEY);
      if (saved === "light" || saved === "dark") setChoice(saved);
    } catch { /* no storage: follow the system */ }
  }, []);
  const choose = (next: Choice) => {
    setChoice(next);
    apply(next);
    try {
      if (next === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, next);
    } catch { /* the choice lasts for this page only */ }
  };
  return (
    <div className="theme-toggle" role="group" aria-label="Theme" data-testid="theme-toggle">
      {CHOICES.map((c) => (
        <button key={c.id} type="button" aria-pressed={choice === c.id} onClick={() => choose(c.id)}>{c.label}</button>
      ))}
    </div>
  );
}

/** Runs before the first paint (root layout): the saved choice, applied with nothing else loaded. */
export const THEME_BOOT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
