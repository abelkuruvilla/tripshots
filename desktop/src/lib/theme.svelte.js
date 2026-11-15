// Light, dark or the system's choice, remembered on this computer. The CSS reads <html data-theme>; with no
// attribute it follows the system. The window's own frame follows too.
import { getCurrentWindow } from "@tauri-apps/api/window";

const KEY = "tripshots.theme";

function load() {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

export const theme = $state({ choice: load() });

export function applyTheme(choice = theme.choice) {
  theme.choice = choice;
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    /* private storage: the choice lasts this session */
  }
  try {  // the window frame follows; never let this stop the app from starting
    getCurrentWindow().setTheme(choice === "system" ? null : choice).catch(() => {});
  } catch {
    /* no native window (a browser preview) */
  }
}
