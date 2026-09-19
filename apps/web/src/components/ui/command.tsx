import * as React from "react";
import { Command as CommandPrimitive } from "cmdk";
import { MagnifyingGlass, X } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

const Command = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive>
>(({ className, ...props }, ref) => <CommandPrimitive ref={ref} className={cn("flex h-full w-full flex-col overflow-hidden rounded-[9px] bg-white text-[var(--ink)]", className)} {...props} />);
Command.displayName = CommandPrimitive.displayName;

const CommandInput = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Input>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>
>(({ className, ...props }, ref) => (
  <div className="flex h-11 items-center gap-2 border-b border-[var(--line)] px-3">
    <MagnifyingGlass size={16} className="shrink-0 text-[var(--muted)]" />
    <CommandPrimitive.Input ref={ref} className={cn("flex h-full w-full bg-transparent text-[14px] outline-none placeholder:text-[var(--muted)]", className)} {...props} />
    <button type="button" className="grid size-7 place-items-center rounded-[5px] text-[var(--muted)] hover:bg-[var(--paper-muted)]" onClick={(event) => { const input = event.currentTarget.parentElement?.querySelector("input"); if (input) { input.value = ""; input.dispatchEvent(new Event("input", { bubbles: true })); input.focus(); } }} aria-label="清除搜索"><X size={14} /></button>
  </div>
));
CommandInput.displayName = CommandPrimitive.Input.displayName;

const CommandList = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>
>(({ className, ...props }, ref) => <CommandPrimitive.List ref={ref} className={cn("max-h-72 overflow-y-auto overflow-x-hidden p-1", className)} {...props} />);
CommandList.displayName = CommandPrimitive.List.displayName;

const CommandEmpty = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Empty>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Empty>
>(({ className, ...props }, ref) => <CommandPrimitive.Empty ref={ref} className={cn("py-6 text-center text-[13px] text-[var(--muted)]", className)} {...props} />);
CommandEmpty.displayName = CommandPrimitive.Empty.displayName;

const CommandGroup = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Group>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>
>(({ className, ...props }, ref) => <CommandPrimitive.Group ref={ref} className={cn("overflow-hidden p-1 text-[var(--ink)] [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[12px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:text-[var(--muted)]", className)} {...props} />);
CommandGroup.displayName = CommandPrimitive.Group.displayName;

const CommandItem = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item>
>(({ className, ...props }, ref) => <CommandPrimitive.Item ref={ref} className={cn("relative flex cursor-default select-none items-center gap-2 rounded-[5px] px-2 py-2 text-[14px] outline-none data-[disabled=true]:pointer-events-none data-[selected=true]:bg-[var(--paper-muted)] data-[disabled=true]:opacity-45", className)} {...props} />);
CommandItem.displayName = CommandPrimitive.Item.displayName;

const CommandSeparator = React.forwardRef<
  React.ElementRef<typeof CommandPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof CommandPrimitive.Separator>
>(({ className, ...props }, ref) => <CommandPrimitive.Separator ref={ref} className={cn("-mx-1 h-px bg-[var(--line)]", className)} {...props} />);
CommandSeparator.displayName = CommandPrimitive.Separator.displayName;

export { Command, CommandInput, CommandList, CommandEmpty, CommandGroup, CommandItem, CommandSeparator };
