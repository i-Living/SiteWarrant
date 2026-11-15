import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

/** A measured value against its maximum; null renders a track with no fill. */
function Progress({
  value,
  max = 100,
  label,
  className,
  indicatorClassName,
  ...props
}: Omit<ComponentProps<"div">, "children"> & {
  value: number | null;
  max?: number;
  /** The progressbar role needs a name; the adjacent text is not one. */
  label: string;
  indicatorClassName?: string;
}) {
  const ratio =
    value === null || max <= 0 ? 0 : Math.min(1, Math.max(0, value / max));
  return (
    <div
      data-slot="progress"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value ?? undefined}
      aria-valuetext={value === null ? "not measured" : undefined}
      className={cn(
        "relative h-1.5 w-full overflow-hidden rounded-full bg-muted",
        className,
      )}
      {...props}
    >
      <div
        data-slot="progress-indicator"
        className={cn("h-full rounded-full bg-foreground", indicatorClassName)}
        style={{ width: `${ratio * 100}%` }}
      />
    </div>
  );
}

export { Progress };
