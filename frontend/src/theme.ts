// Theme management. The theme is stored on <html data-theme="dark|light"> and
// persisted in localStorage under the key the mockups use. An inline <head>
// script applies the saved theme before paint (no flash); this module is the
// runtime API the screens use to read/toggle it and keep the toggle icon synced.

export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "avatar-theme";
const DEFAULT_THEME: Theme = "dark";

/** The current theme from the <html> element (falling back to the default). */
export function getTheme(): Theme {
  const attr = document.documentElement.getAttribute("data-theme");
  return attr === "light" ? "light" : "dark";
}

/** Apply and persist a theme, then refresh any theme-toggle icons on the page. */
export function setTheme(theme: Theme): void {
  const next: Theme = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // localStorage may be unavailable (private mode / blocked cookies); ignore.
  }
  syncThemeIcons();
}

/** Flip between dark and light, returning the new theme. */
export function toggleTheme(): Theme {
  const next: Theme = getTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}

/**
 * Show the moon icon in dark mode and the sun icon in light mode for any
 * theme-toggle button on the page. Buttons use the mockup markup:
 *   <svg class="theme-moon">…</svg><svg class="theme-sun" style="display:none">…</svg>
 */
export function syncThemeIcons(): void {
  const dark = getTheme() === "dark";
  document.querySelectorAll<HTMLElement>(".theme-moon").forEach((el) => {
    el.style.display = dark ? "" : "none";
  });
  document.querySelectorAll<HTMLElement>(".theme-sun").forEach((el) => {
    el.style.display = dark ? "none" : "";
  });
}

/**
 * Ensure the document has a theme applied (in case the inline head script was
 * absent) and sync icons. Safe to call once on screen init.
 */
export function initTheme(): Theme {
  let theme: Theme = DEFAULT_THEME;
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    if (saved === "dark" || saved === "light") theme = saved;
  } catch {
    // ignore
  }
  if (!document.documentElement.getAttribute("data-theme")) {
    document.documentElement.setAttribute("data-theme", theme);
  }
  syncThemeIcons();
  return getTheme();
}

/**
 * Wire a theme-toggle button: clicking it flips and persists the theme.
 * Accepts an element or an element id. Returns a cleanup function.
 */
export function attachThemeToggle(target: HTMLElement | string): () => void {
  const el =
    typeof target === "string" ? document.getElementById(target) : target;
  if (!el) return () => {};
  const handler = () => {
    toggleTheme();
  };
  el.addEventListener("click", handler);
  return () => el.removeEventListener("click", handler);
}
