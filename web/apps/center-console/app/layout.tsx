import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Center 콘솔",
  description: "Chaeksas Center 콘솔 (ADR-0017)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
