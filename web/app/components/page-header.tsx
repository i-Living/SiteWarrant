import type { ReactNode } from "react";
import { cn } from "../lib/utils";

export function PageHeader({
  title,
  description,
  meta,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "mb-5 flex flex-wrap items-start justify-between gap-4",
        className,
      )}
    >
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description !== undefined && (
          <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">
            {description}
          </p>
        )}
        {meta !== undefined && (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
            {meta}
          </div>
        )}
      </div>
      {actions !== undefined && (
        <div className="flex items-center gap-2">{actions}</div>
      )}
    </header>
  );
}
