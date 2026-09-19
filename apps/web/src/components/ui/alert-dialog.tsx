import * as React from "react";
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import { cn } from "@/lib/utils";

const AlertDialog = AlertDialogPrimitive.Root;
const AlertDialogTrigger = AlertDialogPrimitive.Trigger;
const AlertDialogPortal = AlertDialogPrimitive.Portal;
const AlertDialogOverlay = React.forwardRef<React.ElementRef<typeof AlertDialogPrimitive.Overlay>, React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Overlay>>(({ className, ...props }, ref) => <AlertDialogPrimitive.Overlay ref={ref} className={cn("fixed inset-0 z-[130] bg-[rgba(22,24,20,.42)] backdrop-blur-[4px]", className)} {...props} />);
AlertDialogOverlay.displayName = AlertDialogPrimitive.Overlay.displayName;
const AlertDialogContent = React.forwardRef<React.ElementRef<typeof AlertDialogPrimitive.Content>, React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Content>>(({ className, children, ...props }, ref) => <AlertDialogPortal><AlertDialogOverlay /><AlertDialogPrimitive.Content ref={ref} className={cn("fixed left-1/2 top-1/2 z-[131] grid w-[min(460px,calc(100%-2rem))] -translate-x-1/2 -translate-y-1/2 gap-4 rounded-[12px] border border-[var(--line)] bg-white p-6 text-[var(--ink)] shadow-[var(--shadow-float)]", className)} {...props}>{children}</AlertDialogPrimitive.Content></AlertDialogPortal>);
AlertDialogContent.displayName = AlertDialogPrimitive.Content.displayName;
const AlertDialogHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div className={cn("grid gap-1.5", className)} {...props} />;
const AlertDialogFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div className={cn("flex flex-col-reverse gap-2 sm:flex-row sm:justify-end", className)} {...props} />;
const AlertDialogTitle = React.forwardRef<React.ElementRef<typeof AlertDialogPrimitive.Title>, React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Title>>(({ className, ...props }, ref) => <AlertDialogPrimitive.Title ref={ref} className={cn("font-serif text-2xl font-semibold tracking-[-.04em]", className)} {...props} />);
AlertDialogTitle.displayName = AlertDialogPrimitive.Title.displayName;
const AlertDialogDescription = React.forwardRef<React.ElementRef<typeof AlertDialogPrimitive.Description>, React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Description>>(({ className, ...props }, ref) => <AlertDialogPrimitive.Description ref={ref} className={cn("text-[15px] leading-6 text-[var(--muted)]", className)} {...props} />);
AlertDialogDescription.displayName = AlertDialogPrimitive.Description.displayName;
const AlertDialogAction = React.forwardRef<React.ElementRef<typeof AlertDialogPrimitive.Action>, React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Action>>(({ className, ...props }, ref) => <AlertDialogPrimitive.Action ref={ref} className={cn("inline-flex min-h-11 items-center justify-center rounded-[7px] bg-[var(--ink)] px-4 text-[14px] font-semibold text-white transition-colors hover:bg-[var(--vermilion)] focus-visible:ring-2 focus-visible:ring-[var(--focus)]", className)} {...props} />);
AlertDialogAction.displayName = AlertDialogPrimitive.Action.displayName;
const AlertDialogCancel = React.forwardRef<React.ElementRef<typeof AlertDialogPrimitive.Cancel>, React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Cancel>>(({ className, ...props }, ref) => <AlertDialogPrimitive.Cancel ref={ref} className={cn("inline-flex min-h-11 items-center justify-center rounded-[7px] border border-[var(--ink)] bg-white px-4 text-[14px] font-semibold text-[var(--ink)] hover:bg-[var(--paper-muted)] focus-visible:ring-2 focus-visible:ring-[var(--focus)]", className)} {...props} />);
AlertDialogCancel.displayName = AlertDialogPrimitive.Cancel.displayName;

export { AlertDialog, AlertDialogTrigger, AlertDialogPortal, AlertDialogOverlay, AlertDialogContent, AlertDialogHeader, AlertDialogFooter, AlertDialogTitle, AlertDialogDescription, AlertDialogAction, AlertDialogCancel };
