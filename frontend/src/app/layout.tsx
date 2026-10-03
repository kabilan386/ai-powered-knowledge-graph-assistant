import type { Metadata } from "next";
import { Sidebar } from "@/components/layout/sidebar";
import { DocumentSession } from "@/components/documents/document-session";
import "./globals.css";
export const metadata: Metadata = {
  title: "Knowledge Assistant | GraphRAG",
  description:
    "Explore documents, connected knowledge, and grounded answers with citations.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <DocumentSession>
          <a href="#main" className="skip-link">
            Skip to content
          </a>
          <div className="app-shell">
            <Sidebar />
            <main id="main" className="main-content">
              {children}
            </main>
          </div>
        </DocumentSession>
      </body>
    </html>
  );
}
