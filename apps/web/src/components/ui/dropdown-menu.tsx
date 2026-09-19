import * as React from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { Check, CaretRight } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

const DropdownMenu = DropdownMenuPrimitive.Root;
const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;
const DropdownMenuGroup = DropdownMenuPrimitive.Group;
const DropdownMenuPortal = DropdownMenuPrimitive.Portal;
const DropdownMenuSub = DropdownMenuPrimitive.Sub;
const DropdownMenuRadioGroup = DropdownMenuPrimitive.RadioGroup;

const DropdownMenuContent = React.forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.Content>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>>(({ className, sideOffset = 6, ...props }, ref) => <DropdownMenuPrimitive.Portal><DropdownMenuPrimitive.Content ref={ref} sideOffset={sideOffset} className={cn("z-[130] min-w-44 overflow-hidden rounded-[8px] border border-[var(--line)] bg-white p-1 text-[var(--ink)] shadow-[var(--shadow-menu)]", className)} {...props} /></DropdownMenuPrimitive.Portal>);
DropdownMenuContent.displayName = DropdownMenuPrimitive.Content.displayName;

const DropdownMenuItem = React.forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.Item>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & { inset?: boolean }>(({ className, inset, ...props }, ref) => <DropdownMenuPrimitive.Item ref={ref} className={cn("relative flex cursor-default select-none items-center gap-2 rounded-[5px] px-2.5 py-2 text-[14px] outline-none transition-colors focus:bg-[var(--paper-muted)] data-[disabled]:pointer-events-none data-[disabled]:opacity-45", inset && "pl-8", className)} {...props} />);
DropdownMenuItem.displayName = DropdownMenuPrimitive.Item.displayName;

const DropdownMenuCheckboxItem = React.forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.CheckboxItem>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.CheckboxItem>>(({ className, children, checked, ...props }, ref) => <DropdownMenuPrimitive.CheckboxItem ref={ref} checked={checked} className={cn("relative flex cursor-default select-none items-center rounded-[5px] py-2 pl-8 pr-2.5 text-[14px] outline-none focus:bg-[var(--paper-muted)]", className)} {...props}><span className="absolute left-2 inline-flex size-4 items-center justify-center"><DropdownMenuPrimitive.ItemIndicator><Check size={14} weight="bold" /></DropdownMenuPrimitive.ItemIndicator></span>{children}</DropdownMenuPrimitive.CheckboxItem>);
DropdownMenuCheckboxItem.displayName = DropdownMenuPrimitive.CheckboxItem.displayName;

const DropdownMenuLabel = React.forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.Label>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label> & { inset?: boolean }>(({ className, inset, ...props }, ref) => <DropdownMenuPrimitive.Label ref={ref} className={cn("px-2.5 py-1.5 text-[12px] font-semibold text-[var(--muted)]", inset && "pl-8", className)} {...props} />);
DropdownMenuLabel.displayName = DropdownMenuPrimitive.Label.displayName;
const DropdownMenuSeparator = React.forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.Separator>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Separator>>(({ className, ...props }, ref) => <DropdownMenuPrimitive.Separator ref={ref} className={cn("-mx-1 my-1 h-px bg-[var(--line)]", className)} {...props} />);
DropdownMenuSeparator.displayName = DropdownMenuPrimitive.Separator.displayName;
const DropdownMenuSubTrigger = React.forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.SubTrigger>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubTrigger> & { inset?: boolean }>(({ className, inset, children, ...props }, ref) => <DropdownMenuPrimitive.SubTrigger ref={ref} className={cn("flex cursor-default select-none items-center rounded-[5px] px-2.5 py-2 text-[14px] outline-none focus:bg-[var(--paper-muted)]", inset && "pl-8", className)} {...props}>{children}<CaretRight className="ml-auto" size={15} /></DropdownMenuPrimitive.SubTrigger>);
DropdownMenuSubTrigger.displayName = DropdownMenuPrimitive.SubTrigger.displayName;
const DropdownMenuSubContent = React.forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.SubContent>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.SubContent>>(({ className, ...props }, ref) => <DropdownMenuPrimitive.SubContent ref={ref} className={cn("z-[131] min-w-36 overflow-hidden rounded-[8px] border border-[var(--line)] bg-white p-1 text-[var(--ink)] shadow-[var(--shadow-menu)]", className)} {...props} />);
DropdownMenuSubContent.displayName = DropdownMenuPrimitive.SubContent.displayName;

export { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuCheckboxItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuGroup, DropdownMenuPortal, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuRadioGroup };
