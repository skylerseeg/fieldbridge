import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Skyler Seegmiller — Builder, writer, operator.",
  description:
    "Building software, businesses, and stories from Salt Lake City. Find me anywhere.",
  metadataBase: new URL("https://skylerseegmiller.com"),
  openGraph: {
    title: "Skyler Seegmiller",
    description: "Builder, writer, operator. Salt Lake City.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-ink text-bone antialiased">{children}</body>
    </html>
  );
}
