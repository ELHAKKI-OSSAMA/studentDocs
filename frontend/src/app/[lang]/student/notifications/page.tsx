"use client";

import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/page";
import { MarkAllRead, NotificationList } from "@/components/notifications";
import { useI18n } from "@/i18n/client";

export default function NotificationsPage() {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t("notifications.title")} actions={<MarkAllRead />} />
      <Card>
        <CardContent>
          <NotificationList area="student" />
        </CardContent>
      </Card>
    </>
  );
}
