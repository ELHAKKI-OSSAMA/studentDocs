"use client";

import type { ReactNode } from "react";
import {
  BellIcon,
  FileTextIcon,
  FolderOpenIcon,
  LayoutDashboardIcon,
  ListChecksIcon,
  UserIcon,
} from "lucide-react";
import { AppShell, type NavSection } from "@/components/app-shell";
import { AuthGuard } from "@/components/auth-guard";

const sections: NavSection[] = [
  {
    items: [
      { href: "/student", label: "nav.dashboard", icon: LayoutDashboardIcon, exact: true },
      { href: "/student/new-request", label: "nav.newRequest", icon: FileTextIcon },
      { href: "/student/requests", label: "nav.myRequests", icon: ListChecksIcon },
      { href: "/student/documents", label: "nav.documents", icon: FolderOpenIcon },
      { href: "/student/notifications", label: "nav.notifications", icon: BellIcon },
      { href: "/student/profile", label: "nav.profile", icon: UserIcon },
    ],
  },
];

export default function StudentLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard area="student">
      {(me) => (
        <AppShell area="student" me={me} sections={sections} subtitle="nav.studentPortal">
          {children}
        </AppShell>
      )}
    </AuthGuard>
  );
}
