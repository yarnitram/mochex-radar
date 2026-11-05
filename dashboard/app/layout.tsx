import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Mochex Radar",
  description: "Crypto market context and Solana research observations",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
