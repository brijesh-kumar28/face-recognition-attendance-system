"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth-store";
import {
  LayoutDashboard,
  Users,
  Brain,
  ClipboardList,
  BarChart3,
  LogOut,
  ChevronLeft,
  ScanFace,
} from "lucide-react";
import { Button } from "@/components/ui/button";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const adminLinks = [
  { href: "/admin", label: "Dashboard", icon: LayoutDashboard },
  { href: "/admin/users", label: "Manage Users", icon: Users },
  { href: "/admin/train", label: "Train Model", icon: Brain },
  { href: "/admin/group-scan", label: "Group Scan", icon: ScanFace },
  { href: "/admin/attendance", label: "Attendance", icon: ClipboardList },
  { href: "/admin/reports", label: "Reports", icon: BarChart3 },
];

const userLinks = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/dashboard/records", label: "My Records", icon: ClipboardList },
  { href: "/dashboard/profile", label: "Profile", icon: Users },
];

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const isAdmin = user?.role === "admin";
  const links = isAdmin ? adminLinks : userLinks;

  const handleLogout = () => {
    logout();
    router.push("/");
  };

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-40 flex h-screen flex-col border-r bg-card transition-all duration-300",
        collapsed ? "w-16" : "w-64"
      )}
    >
      {/* Header */}
      <div className="flex h-16 items-center justify-between border-b px-4">
        {!collapsed && (
          <Link href={isAdmin ? "/admin" : "/dashboard"} className="flex items-center gap-2">
            <ScanFace className="h-7 w-7 text-primary" />
            <span className="text-lg font-bold text-primary">FaceTrack</span>
          </Link>
        )}
        {collapsed && (
          <Link href={isAdmin ? "/admin" : "/dashboard"} className="mx-auto">
            <ScanFace className="h-7 w-7 text-primary" />
          </Link>
        )}
      </div>

      {/* Toggle */}
      <Button
        variant="ghost"
        size="icon"
        onClick={onToggle}
        className="absolute -right-3 top-20 z-50 h-6 w-6 rounded-full border bg-background shadow-md"
      >
        <ChevronLeft
          className={cn(
            "h-3 w-3 transition-transform",
            collapsed && "rotate-180"
          )}
        />
      </Button>

      {/* Nav */}
      <nav className="flex-1 space-y-1 overflow-y-auto p-3">
        {links.map((link) => {
          const isActive =
            pathname === link.href ||
            (link.href !== (isAdmin ? "/admin" : "/dashboard") &&
              pathname.startsWith(link.href));
          return (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
                collapsed && "justify-center px-2"
              )}
              title={collapsed ? link.label : undefined}
            >
              <link.icon className="h-5 w-5 shrink-0" />
              {!collapsed && <span>{link.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="border-t p-3">
        <button
          onClick={handleLogout}
          className={cn(
            "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive",
            collapsed && "justify-center px-2"
          )}
        >
          <LogOut className="h-5 w-5 shrink-0" />
          {!collapsed && <span>Logout</span>}
        </button>
      </div>
    </aside>
  );
}
