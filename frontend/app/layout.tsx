import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { routes } from "../lib/routes";

import "./globals.css";

export const metadata: Metadata = {
  title: "Atlas Research",
  description: "Evidence-driven investment research",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#atlas-root">
          Skip to content
        </a>
        <header>
          <nav aria-label="Site">
            <ul className="nav-reader">
              <li>
                <Link href={routes.home}>Research</Link>
              </li>
              <li>
                <Link href={routes.hypotheses}>Hypotheses</Link>
              </li>
              <li>
                <Link href={routes.companies}>Companies</Link>
              </li>
            </ul>
            <ul className="nav-ops" aria-label="Operations">
              <li>
                <Link href={routes.memory}>Memory</Link>
              </li>
              <li>
                <Link href={routes.relationships()}>Relationships</Link>
              </li>
              <li>
                <Link href={routes.exceptions}>Exceptions queue</Link>
              </li>
              <li>
                <Link href={routes.workbench}>Research workbench</Link>
              </li>
              <li>
                <Link href={routes.themes}>Themes</Link>
              </li>
            </ul>
          </nav>
        </header>
        <main id="atlas-root">{children}</main>
      </body>
    </html>
  );
}
