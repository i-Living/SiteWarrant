import { statusLabel, statusNote } from "../lib/format";
import { statusStyle } from "../lib/severity";
import { cn } from "../lib/utils";
import { Badge } from "./ui/badge";

export function StatusStamp({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  return (
    <Badge
      variant="outline"
      title={statusNote(status)}
      className={cn("gap-1.5 capitalize", statusStyle(status), className)}
    >
      <span
        aria-hidden="true"
        className={cn(
          "size-1.5 rounded-full bg-current",
          status === "running" && "animate-pulse",
        )}
      />
      {statusLabel(status)}
    </Badge>
  );
}
