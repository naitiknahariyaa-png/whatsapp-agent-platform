import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "ChainAI | Decentralized Web3 Artificial Intelligence Core",
  description: "Unleash the power of Blockchain AI. Real-time smart contract audits, blockchain technical analysis, and automated market intelligence powered by ChainAI.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${spaceGrotesk.variable} h-full antialiased no-scrollbar`}
    >
      <body className="bg-dark-bg text-slate-100 min-h-full font-sans antialiased selection:bg-neon-purple/30 selection:text-white">
        {children}
      </body>
    </html>
  );
}
