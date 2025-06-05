import type { Metadata } from "next";
// import { Geist, Geist_Mono } from "next/font/google"; // Comment out or remove Geist if not used
import { Quantico } from "next/font/google"; // Import Quantico
import "./globals.css";

// const geistSans = Geist({ // Comment out or remove Geist if not used
//   variable: "--font-geist-sans",
//   subsets: ["latin"],
// });

// const geistMono = Geist_Mono({ // Comment out or remove Geist if not used
//   variable: "--font-geist-mono",
//   subsets: ["latin"],
// });

// Configure Quantico font
const quantico = Quantico({
  variable: "--font-quantico",
  weight: ["400", "700"], // Regular and Bold weights
  subsets: ["latin"],
  display: "swap", // Recommended font display strategy
});

export const metadata: Metadata = {
  title: "Agentic Monopoly v0.1", // Updated title
  description: "View live Monopoly game data and agent decisions.", // Updated description
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${quantico.variable} antialiased`}
        // If Geist fonts are still needed for other parts, add them back:
        // className={`${quantico.variable} ${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
