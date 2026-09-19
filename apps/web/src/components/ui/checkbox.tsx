import * as React from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

const Checkbox = React.forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root ref={ref} className={cn("peer size-[18px] shrink-0 rounded-[4px] border border-[var(--line-strong)] bg-white outline-none transition-[background-color,border-color,transform] focus-visible:ring-2 focus-visible:ring-[rgba(181,51,42,.28)] data-[state=checked]:border-[var(--vermilion)] data-[state=checked]:bg-[var(--vermilion)] active:scale-[.96]", className)} {...props}>
    <CheckboxPrimitive.Indicator className="grid place-items-center text-white"><Check size={13} weight="bold" /></CheckboxPrimitive.Indicator>
  </CheckboxPrimitive.Root>
));
Checkbox.displayName = CheckboxPrimitive.Root.displayName;

export { Checkbox };
