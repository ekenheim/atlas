import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

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
            <Link href="/">Atlas Research</Link>
            <span aria-hidden="true"> · </span>
            <span>Source viewer</span>
          </nav>
        </header>
        <main id="atlas-root">{children}</main>
      </body>
    </html>
  );
}
