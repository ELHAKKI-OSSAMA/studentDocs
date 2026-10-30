"use client";

import type { ReactNode } from "react";
import {
  BadgeCheckIcon,
  CalendarRangeIcon,
  FileStackIcon,
  FolderTreeIcon,
  GitBranchIcon,
  InboxIcon,
  LayersIcon,
  LayoutDashboardIcon,
  MailIcon,
  ScrollTextIcon,
  SettingsIcon,
  UserCogIcon,
  UsersIcon,
} from "lucide-react";
import { AppShell, type NavSection } from "@/components/app-shell";
import { AuthGuard } from "@/components/auth-guard";

const sections: NavSection[] = [
  {
    items: [
      { href: "/admin", label: "nav.dashboard", icon: LayoutDashboardIcon, exact: true },
      { href: "/admin/requests", label: "nav.requests", icon: InboxIcon, permission: "requests.read" },
      {
        href: "/admin/enrollments",
        label: "nav.enrollments",
        icon: BadgeCheckIcon,
        permission: "enrollments.verify",
      },
      { href: "/admin/emails", label: "nav.emails", icon: MailIcon, permission: "emails.read" },
      { href: "/admin/students", label: "nav.students", icon: UsersIcon, permission: "students.read" },
    ],
  },
  {
    title: "nav.sectionCatalog",
    items: [
      { href: "/admin/academic-years", label: "nav.academicYears", icon: CalendarRangeIcon },
      { href: "/admin/branch-categories", label: "nav.branchCategories", icon: FolderTreeIcon },
      { href: "/admin/branches", label: "nav.branches", icon: GitBranchIcon },
      { href: "/admin/study-levels", label: "nav.studyLevels", icon: LayersIcon },
      { href: "/admin/document-types", label: "nav.documentTypes", icon: FileStackIcon },
    ],
  },
  {
    title: "nav.sectionAdministration",
    items: [
      { href: "/admin/users", label: "nav.users", icon: UserCogIcon, permission: "users.read" },
      { href: "/admin/audit-logs", label: "nav.auditLogs", icon: ScrollTextIcon },
      { href: "/admin/settings", label: "nav.settings", icon: SettingsIcon, permission: "settings.manage" },
    ],
  },
];

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard area="admin">
      {(me) => (
        <AppShell area="admin" me={me} sections={sections} subtitle="nav.adminPortal">
          {children}
        </AppShell>
      )}
    </AuthGuard>
  );
}

