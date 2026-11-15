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
  // Zero findings over zero findings is not a proportion: with no denominator the widget says
  // "not measured" instead of announcing a value it does not have.
  const measured = value !== null && max > 0;
  const ratio = measured ? Math.min(1, Math.max(0, value / max)) : 0;
  return (
    <div
      data-slot="progress"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={measured ? max : undefined}
      aria-valuenow={measured ? value : undefined}
      aria-valuetext={measured ? undefined : "not measured"}
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
