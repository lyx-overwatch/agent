import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";
import "./styles/markdown.scss";

export const metadata: Metadata = {
  title: "Heyu Agent",
  description: "Heyu Agent AI Agent 平台",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="h-full flex flex-col">
        {children}
        <Toaster />
      </body>
    </html>
  );
}
