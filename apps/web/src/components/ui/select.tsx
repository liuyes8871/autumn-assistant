import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, CaretDown, CaretUp } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

const Select = SelectPrimitive.Root;
const SelectGroup = SelectPrimitive.Group;
const SelectValue = SelectPrimitive.Value;

const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger ref={ref} className={cn("flex h-11 w-full items-center justify-between gap-2 rounded-[7px] border border-[var(--line)] bg-white px-3 text-left text-[15px] text-[var(--ink)] outline-none transition-[border-color,box-shadow] focus:border-[var(--vermilion)] focus:ring-2 focus:ring-[rgba(181,51,42,.16)] disabled:cursor-not-allowed disabled:opacity-50", className)} {...props}>
    {children}
    <SelectPrimitive.Icon asChild><CaretDown size={16} weight="bold" className="shrink-0 text-[var(--muted)]" /></SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;

const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content ref={ref} className={cn("relative z-[120] max-h-80 min-w-[9rem] overflow-hidden rounded-[9px] border border-[var(--line-strong)] bg-white p-1 text-[var(--ink)] shadow-[0_18px_48px_rgba(22,24,20,.16)] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[side=bottom]:slide-in-from-top-2", position === "popper" && "data-[side=bottom]:translate-y-1", className)} position={position} {...props}>
      <SelectPrimitive.ScrollUpButton className="flex h-7 items-center justify-center bg-white"><CaretUp size={15} /></SelectPrimitive.ScrollUpButton>
      <SelectPrimitive.Viewport className="p-0.5">{children}</SelectPrimitive.Viewport>
      <SelectPrimitive.ScrollDownButton className="flex h-7 items-center justify-center bg-white"><CaretDown size={15} /></SelectPrimitive.ScrollDownButton>
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = SelectPrimitive.Content.displayName;

const SelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => <SelectPrimitive.Label ref={ref} className={cn("px-2 py-1.5 text-[12px] font-semibold text-[var(--muted)]", className)} {...props} />);
SelectLabel.displayName = SelectPrimitive.Label.displayName;

const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Item ref={ref} className={cn("relative flex w-full cursor-default select-none items-center rounded-[5px] py-2 pl-8 pr-2 text-[14px] outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-[var(--paper-muted)] data-[disabled]:opacity-45", className)} {...props}>
    <span className="absolute left-2 flex size-4 items-center justify-center"><SelectPrimitive.ItemIndicator><Check size={14} weight="bold" /></SelectPrimitive.ItemIndicator></span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
));
SelectItem.displayName = SelectPrimitive.Item.displayName;

const SelectSeparator = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => <SelectPrimitive.Separator ref={ref} className={cn("-mx-1 my-1 h-px bg-[var(--line)]", className)} {...props} />);
SelectSeparator.displayName = SelectPrimitive.Separator.displayName;

export { Select, SelectGroup, SelectValue, SelectTrigger, SelectContent, SelectLabel, SelectItem, SelectSeparator };
