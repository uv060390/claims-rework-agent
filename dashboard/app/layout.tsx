import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { DEMO_MODE } from "@/lib/data";

export const metadata: Metadata = {
  title: "Claims Rework — Analyst Console",
  description:
    "Human-in-the-loop console for the Recommend-then-Release agentic claims rework pipeline (synthetic data).",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <div className="topbar">
            <h1>
              <Link href="/">Claims Rework · Analyst Console</Link>
            </h1>
            <span className="sub">
              Recommend-then-Release pipeline · synthetic data ·{" "}
              <a
                href="https://github.com/uv060390/claims-rework-agent"
                style={{ textDecoration: "underline" }}
              >
                source
              </a>
            </span>
          </div>
          {DEMO_MODE && (
            <div className="demo-banner">
              Demo snapshot — a frozen batch run of the real pipeline (Claude triage included) on
              synthetic claims. Approve/Reject actions are simulated client-side.
            </div>
          )}
          {children}
        </div>
      </body>
    </html>
  );
}
