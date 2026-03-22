import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import NextAuthSessionProvider from "@/components/session-provider";
import Navbar from "@/components/navbar";
import { ToastProvider } from "@/components/toast";
import { ThemeProvider } from "@/components/theme-provider";
import { DevModeProvider } from "@/components/dev-mode-provider";
import DevPanel from "@/components/dev-panel";
import "./globals.css";

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "SignalRank",
  description: "Deterministic job ranking engine",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${jetbrainsMono.variable} h-full`}>
      <body className="min-h-full flex flex-col antialiased">
        <NextAuthSessionProvider>
          <ThemeProvider>
            <DevModeProvider>
              <ToastProvider>
                <Navbar />
                <DevPanel />
                {children}
              </ToastProvider>
            </DevModeProvider>
          </ThemeProvider>
        </NextAuthSessionProvider>
      </body>
    </html>
  );
}
