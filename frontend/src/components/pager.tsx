"use client";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n/client";

export function Pager({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
}) {
  const { t } = useI18n();
  if (total <= limit) return null;
  return (
    <div className="mt-4 flex items-center justify-between gap-2 text-sm text-muted-foreground">
      <span className="tabular-nums">
        {t("common.pageOf", { from: offset + 1, to: Math.min(offset + limit, total), total })}
      </span>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          {t("common.previous")}
        </Button>
        <Button variant="outline" size="sm" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
          {t("common.next")}
        </Button>
      </div>
    </div>
  );
}
