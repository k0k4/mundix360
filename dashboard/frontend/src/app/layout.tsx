import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";

export const metadata: Metadata = {
  title: "Mundix Security 360",
  description: "Plataforma unificada de segurança, visibilidade e compliance de rede.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className="dark">
      <body>
        <Sidebar />
        <main className="ml-60 min-h-screen px-8 py-7">{children}</main>
      </body>
    </html>
  );
}
