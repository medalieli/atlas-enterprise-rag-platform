import type { Metadata } from "next";
import "./styles.css";
export const metadata: Metadata = { title: "Atlas Knowledge", description: "Secure enterprise knowledge assistant" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
