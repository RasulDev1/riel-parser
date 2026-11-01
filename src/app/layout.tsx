import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Парсер недвижимости Авито",
  description: "Сбор объявлений о недвижимости с Авито по цене, городу, району, площади и этажам",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">{children}</body>
    </html>
  );
}
