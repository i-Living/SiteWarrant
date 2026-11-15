import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

function Avatar({ className, ...props }: ComponentProps<"span">) {
  return (
    <span
      data-slot="avatar"
      className={cn(
        "inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary text-[11px] font-medium text-secondary-foreground",
        className,
      )}
      {...props}
    />
  );
}

export { Avatar };
