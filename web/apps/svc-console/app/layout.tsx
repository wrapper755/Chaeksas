import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "서비스 앱 관리 콘솔",
  description: "Chaeksas 서비스 앱 관리 콘솔 (ADR-0017)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
