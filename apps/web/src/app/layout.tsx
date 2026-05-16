import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import NavBar from "./components/NavBar";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Project Sunday",
  description: "Your personal AI assistant",
  applicationName: "Project Sunday",
  appleWebApp: { capable: true, statusBarStyle: "default", title: "Project Sunday" },
};

export const viewport: Viewport = {
  themeColor: "#01696f",
  width: "device-width",
  initialScale: 1,
  // maximumScale removed — pinch-to-zoom is an a11y requirement.
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning data-scroll-behavior="smooth" className={inter.variable}>
      <body style={{ fontFamily: "var(--font-inter), system-ui, sans-serif" }}>
        <NavBar />
        <main style={{ minHeight: "calc(100dvh - 56px)" }}>{children}</main>
      </body>
    </html>
  );
}