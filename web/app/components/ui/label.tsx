import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

function Label({ className, ...props }: ComponentProps<"label">) {
  return (
    // biome-ignore lint/a11y/noLabelWithoutControl: every caller supplies htmlFor.
    <label
      data-slot="label"
      className={cn(
        "flex items-center gap-2 text-sm font-medium leading-none select-none",
        "peer-disabled:pointer-events-none peer-disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Label };
