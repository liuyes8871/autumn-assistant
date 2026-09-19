import * as React from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import { X } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

const ToastProvider = ToastPrimitive.Provider;
const ToastViewport = React.forwardRef<React.ElementRef<typeof ToastPrimitive.Viewport>, React.ComponentPropsWithoutRef<typeof ToastPrimitive.Viewport>>(({ className, ...props }, ref) => <ToastPrimitive.Viewport ref={ref} className={cn("fixed bottom-4 right-4 z-[150] flex w-[min(380px,calc(100%-2rem))] flex-col gap-2 outline-none", className)} {...props} />);
ToastViewport.displayName = ToastPrimitive.Viewport.displayName;
const Toast = React.forwardRef<React.ElementRef<typeof ToastPrimitive.Root>, React.ComponentPropsWithoutRef<typeof ToastPrimitive.Root>>(({ className, ...props }, ref) => <ToastPrimitive.Root ref={ref} className={cn("group relative flex items-start gap-3 overflow-hidden rounded-[8px] border border-[var(--line)] bg-white p-4 text-[var(--ink)] shadow-[var(--shadow-float)] data-[state=closed]:animate-out data-[state=closed]:fade-out-80 data-[state=open]:animate-in data-[state=open]:fade-in-0", className)} {...props} />);
Toast.displayName = ToastPrimitive.Root.displayName;
const ToastAction = React.forwardRef<React.ElementRef<typeof ToastPrimitive.Action>, React.ComponentPropsWithoutRef<typeof ToastPrimitive.Action>>(({ className, ...props }, ref) => <ToastPrimitive.Action ref={ref} className={cn("rounded-[6px] border border-[var(--ink)] px-3 py-1.5 text-[13px] font-semibold hover:bg-[var(--paper-muted)]", className)} {...props} />);
ToastAction.displayName = ToastPrimitive.Action.displayName;
const ToastClose = React.forwardRef<React.ElementRef<typeof ToastPrimitive.Close>, React.ComponentPropsWithoutRef<typeof ToastPrimitive.Close>>(({ className, ...props }, ref) => <ToastPrimitive.Close ref={ref} className={cn("absolute right-2 top-2 inline-grid size-8 place-items-center rounded-[6px] text-[var(--muted)] hover:bg-[var(--paper-muted)] hover:text-[var(--vermilion)]", className)} toast-close=""><X size={15} aria-hidden="true" /> <span className="sr-only">关闭</span></ToastPrimitive.Close>);
ToastClose.displayName = ToastPrimitive.Close.displayName;
const ToastTitle = React.forwardRef<React.ElementRef<typeof ToastPrimitive.Title>, React.ComponentPropsWithoutRef<typeof ToastPrimitive.Title>>(({ className, ...props }, ref) => <ToastPrimitive.Title ref={ref} className={cn("pr-5 text-[15px] font-semibold", className)} {...props} />);
ToastTitle.displayName = ToastPrimitive.Title.displayName;
const ToastDescription = React.forwardRef<React.ElementRef<typeof ToastPrimitive.Description>, React.ComponentPropsWithoutRef<typeof ToastPrimitive.Description>>(({ className, ...props }, ref) => <ToastPrimitive.Description ref={ref} className={cn("pr-5 text-[14px] leading-5 text-[var(--muted)]", className)} {...props} />);
ToastDescription.displayName = ToastPrimitive.Description.displayName;

export { ToastProvider, ToastViewport, Toast, ToastTitle, ToastDescription, ToastClose, ToastAction };
