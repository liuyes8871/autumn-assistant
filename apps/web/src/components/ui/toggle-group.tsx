import * as React from "react";
import * as ToggleGroupPrimitive from "@radix-ui/react-toggle-group";
import { cn } from "@/lib/utils";

const ToggleGroupContext = React.createContext<{ size?: "sm" | "default" | "lg"; variant?: "default" | "outline" }>({});

const ToggleGroup = React.forwardRef<React.ElementRef<typeof ToggleGroupPrimitive.Root>, React.ComponentPropsWithoutRef<typeof ToggleGroupPrimitive.Root> & { size?: "sm" | "default" | "lg"; variant?: "default" | "outline" }>((({ className, size, variant, children, ...props }, ref) => <ToggleGroupPrimitive.Root ref={ref} className={cn("flex items-center justify-center gap-1", className)} {...props}><ToggleGroupContext.Provider value={{ size, variant }}>{children}</ToggleGroupContext.Provider></ToggleGroupPrimitive.Root>));
ToggleGroup.displayName = ToggleGroupPrimitive.Root.displayName;

const ToggleGroupItem = React.forwardRef<React.ElementRef<typeof ToggleGroupPrimitive.Item>, React.ComponentPropsWithoutRef<typeof ToggleGroupPrimitive.Item>>(({ className, children, ...props }, ref) => {
  const { size = "default", variant = "default" } = React.useContext(ToggleGroupContext);
  return <ToggleGroupPrimitive.Item ref={ref} className={cn("inline-flex min-h-10 items-center justify-center border border-transparent px-3 text-[14px] font-semibold outline-none transition-colors focus-visible:ring-2 focus-visible:ring-[var(--focus)] disabled:pointer-events-none disabled:opacity-45 data-[state=on]:bg-[var(--vermilion)] data-[state=on]:text-white", variant === "outline" && "border-[var(--line)] bg-white text-[var(--ink-soft)] data-[state=on]:border-[var(--vermilion)]", size === "sm" && "min-h-8 px-2 text-[13px]", size === "lg" && "min-h-12 px-5 text-[15px]", className)} {...props}>{children}</ToggleGroupPrimitive.Item>;
});
ToggleGroupItem.displayName = ToggleGroupPrimitive.Item.displayName;

export { ToggleGroup, ToggleGroupItem };
