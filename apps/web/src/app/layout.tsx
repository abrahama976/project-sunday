import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import NavBar from "./components/NavBar";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
  display: "swap",
  variable: "--font-inter",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: "Project Sunday",
  description: "Your personal AI assistant",
  applicationName: "Project Sunday",
  appleWebApp: { capable: true, statusBarStyle: "black-translucent", title: "Project Sunday" },
};

export const viewport: Viewport = {
  themeColor: "#121110",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  // maximumScale removed — pinch-to-zoom is an a11y requirement.
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body>
        <NavBar />
        <main style={{
          minHeight: "calc(100dvh - var(--nav-top-h) - var(--nav-bottom-h) - var(--safe-area-bottom))",
          paddingBottom: "calc(var(--nav-bottom-h) + var(--safe-area-bottom))",
        }}>{children}</main>
      </body>
    </html>
  );
}