import type { Metadata, Viewport } from "next";
import { Archivo, B612_Mono } from "next/font/google";
import { ViewTransition } from "react";
import "./globals.css";

const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  axes: ["wdth"],
  display: "swap",
});

// B612 was drawn by Airbus for cockpit displays; we use the mono cut for every
// code, time and amount on screen.
const b612Mono = B612_Mono({
  variable: "--font-b612-mono",
  subsets: ["latin"],
  weight: ["400", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://stormcheck-chi.vercel.app"),
  title: "StormCheck — the disruption-liability seat",
  description:
    "The morning after every storm, StormCheck works out the real cause of each cancelled flight from real weather and the aircraft's own logs, and drafts what every passenger is owed.",
};

export const viewport: Viewport = {
  themeColor: "#0b0e13",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${archivo.variable} ${b612Mono.variable} antialiased`}>
      <body>
        <ViewTransition>{children}</ViewTransition>
      </body>
    </html>
  );
}
