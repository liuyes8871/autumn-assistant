import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

const Sheet = DialogPrimitive.Root;
const SheetTrigger = DialogPrimitive.Trigger;
const SheetClose = DialogPrimitive.Close;
const SheetPortal = DialogPrimitive.Portal;

const SheetOverlay = React.forwardRef<React.ElementRef<typeof DialogPrimitive.Overlay>, React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>>(({ className, ...props }, ref) => <DialogPrimitive.Overlay ref={ref} className={cn("fixed inset-0 z-[120] bg-[rgba(22,24,20,.42)] backdrop-blur-[4px] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0", className)} {...props} />);
SheetOverlay.displayName = DialogPrimitive.Overlay.displayName;

const SheetContent = React.forwardRef<React.ElementRef<typeof DialogPrimitive.Content>, React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { side?: "top" | "right" | "bottom" | "left" }>(({ side = "right", className, children, ...props }, ref) => {
  const sideClass = {
    top: "inset-x-0 top-0 border-b data-[state=closed]:slide-out-to-top data-[state=open]:slide-in-from-top",
    bottom: "inset-x-0 bottom-0 border-t data-[state=closed]:slide-out-to-bottom data-[state=open]:slide-in-from-bottom",
    left: "inset-y-0 left-0 h-full w-3/4 border-r data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left sm:max-w-sm",
    right: "inset-y-0 right-0 h-full w-3/4 border-l data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right sm:max-w-sm",
  }[side];
  return <SheetPortal><SheetOverlay /><DialogPrimitive.Content ref={ref} className={cn("fixed z-[121] flex flex-col gap-4 overflow-y-auto border-[var(--line)] bg-white p-6 text-[var(--ink)] shadow-[var(--shadow-float)] outline-none transition ease-in-out data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:duration-200 data-[state=open]:duration-200", sideClass, className)} {...props}>{children}<DialogPrimitive.Close className="absolute right-4 top-4 inline-grid size-10 place-items-center rounded-[7px] text-[var(--muted)] hover:bg-[var(--paper-muted)] hover:text-[var(--vermilion)] focus-visible:ring-2 focus-visible:ring-[var(--focus)]"><X size={18} weight="bold" aria-hidden="true" /><span className="sr-only">关闭</span></DialogPrimitive.Close></DialogPrimitive.Content></SheetPortal>;
});
SheetContent.displayName = DialogPrimitive.Content.displayName;

const SheetHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div className={cn("grid gap-1.5", className)} {...props} />;
const SheetFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div className={cn("mt-auto flex flex-col gap-2", className)} {...props} />;
const SheetTitle = React.forwardRef<React.ElementRef<typeof DialogPrimitive.Title>, React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>>(({ className, ...props }, ref) => <DialogPrimitive.Title ref={ref} className={cn("font-serif text-2xl font-semibold tracking-[-.04em]", className)} {...props} />);
SheetTitle.displayName = DialogPrimitive.Title.displayName;
const SheetDescription = React.forwardRef<React.ElementRef<typeof DialogPrimitive.Description>, React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>>(({ className, ...props }, ref) => <DialogPrimitive.Description ref={ref} className={cn("text-[15px] leading-6 text-[var(--muted)]", className)} {...props} />);
SheetDescription.displayName = DialogPrimitive.Description.displayName;

export { Sheet, SheetPortal, SheetOverlay, SheetTrigger, SheetClose, SheetContent, SheetHeader, SheetFooter, SheetTitle, SheetDescription };
