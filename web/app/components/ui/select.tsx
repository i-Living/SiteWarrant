import { ChevronDown } from "lucide-react";
import type { ComponentProps } from "react";
import { cn } from "../../lib/utils";

function Select({ className, children, ...props }: ComponentProps<"select">) {
  return (
    <span data-slot="select" className="relative inline-flex">
      <select
        className={cn(
          "h-9 w-full appearance-none rounded-md border border-input bg-transparent py-1 pr-8 pl-3 text-sm shadow-xs outline-none",
          "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
          "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-muted-foreground"
      />
    </span>
  );
}

export { Select };
