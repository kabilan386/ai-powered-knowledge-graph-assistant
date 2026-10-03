"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/ui/icon";
const items = [
  { href: "/chat", label: "Chat", icon: "chat" },
  { href: "/documents", label: "Documents", icon: "document" },
  { href: "/graph", label: "Knowledge Graph", icon: "graph" },
] as const;
export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sidebar">
      <Link href="/chat" className="brand">
        <span className="brand-mark">
          <Icon name="graph" width={25} height={25} />
        </span>
        <span>
          Knowledge
          <span className="block font-normal text-muted">Assistant</span>
        </span>
      </Link>
      <p className="sidebar-caption">WORKSPACE</p>
      <nav aria-label="Main navigation">
        {items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            aria-current={pathname === item.href ? "page" : undefined}
            className={`nav-link ${pathname === item.href ? "active" : ""}`}
          >
            <Icon name={item.icon} />
            {item.label}
            {pathname === item.href && <span className="nav-dot" />}
          </Link>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="mb-3 flex items-center gap-2 text-ink">
          <Icon name="graph" /> Connected knowledge
        </div>
        <p>Documents, relationships, and answers in one workspace.</p>
        <span className="mt-4 block text-xs">MCA PROJECT · GRAPHRAG</span>
      </div>
    </aside>
  );
}
