import type { Metadata } from "next";
import { IBM_Plex_Mono, Inter } from "next/font/google";
import Link from "next/link";

import { AnalystDrawer } from "@/components/analyst";
import { WorkspaceSwitcher } from "@/components/nav";

import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const plexMono = IBM_Plex_Mono({ variable: "--font-plex-mono", subsets: ["latin"], weight: ["400", "500"] });

export const metadata: Metadata = {
  title: "ATLAS · Marketing decisions",
  description: "From marketing performance to marketing decisions, with the evidence behind every number.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${plexMono.variable} antialiased`}>
      <body className="min-h-screen">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <Link href="/halden" className="flex items-baseline gap-2">
              <span className="text-base font-semibold tracking-tight">ATLAS</span>
              <span className="hidden text-xs text-muted sm:inline">Marketing measurement &amp; decisions</span>
            </Link>
            <WorkspaceSwitcher />
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</main>
        <footer className="mx-auto max-w-7xl px-4 pb-10 text-xs text-muted sm:px-6">
          The three workspaces are never joined. Halden Coffee Works is a fictional, simulated company; its numbers
          make no claim about any real business.
        </footer>
        <AnalystDrawer />
      </body>
    </html>
  );
}
