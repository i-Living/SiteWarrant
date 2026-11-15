import type { ReactNode } from "react";
import { Card, CardContent, CardDescription } from "./ui/card";

export function Kpi({
  label,
  value,
  hint,
  children,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <Card className="gap-2 py-3.5">
      <CardContent className="flex flex-col gap-2 px-4">
        <CardDescription className="text-xs">{label}</CardDescription>
        <p className="text-2xl font-semibold tracking-tight tabular-nums">
          {value}
        </p>
        {children ?? <p className="text-xs text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}
