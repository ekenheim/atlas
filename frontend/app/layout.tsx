import type { Metadata } from "next";
import type { ReactNode } from "react";

import { SiteNav } from "../components/site-nav";

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
          <SiteNav />
        </header>
        <main id="atlas-root">{children}</main>
      </body>
    </html>
  );
}
