// The site navigation (spec §2): five items, and which one is current for a path. System is
// everything that is not one of the other four, so every route stays reachable.
import { routes } from "./routes";

export type Section = "today" | "themes" | "record" | "decide" | "system";

export interface NavItem {
  section: Section;
  label: string;
  href: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { section: "today", label: "Today", href: routes.home },
  { section: "themes", label: "Themes", href: routes.themes },
  { section: "record", label: "Record", href: routes.record },
  { section: "decide", label: "Decide", href: routes.decide },
  { section: "system", label: "System", href: routes.system },
];

/** A route is under `/name` when it is `/name` or `/name/...` (so `/themes` is not `/theme`). */
const under = (path: string, name: string) => path === name || path.startsWith(`${name}/`);

const THEME_ROUTES = [
  "/themes",
  "/theme",
  "/hypothesis",
  "/belief",
  "/company",
  "/chokepoint",
  "/watch-run",
];

/** The section a path belongs to. The path is `location.pathname`: `/`, `/theme/`, `/memory/`. */
export function sectionOf(pathname: string): Section {
  const path = pathname === "/" ? "/" : pathname.replace(/\/+$/, "");
  if (path === "/" || path === "") return "today";
  if (THEME_ROUTES.some((name) => under(path, name))) return "themes";
  if (under(path, "/record")) return "record";
  if (under(path, "/decide")) return "decide";
  return "system";
}
