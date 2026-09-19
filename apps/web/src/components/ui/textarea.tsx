import * as React from "react";
import { cn } from "@/lib/utils";

const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => <textarea ref={ref} className={cn("flex min-h-24 w-full resize-y rounded-[7px] border border-[var(--line)] bg-white px-3 py-2.5 text-[15px] text-[var(--ink)] outline-none placeholder:text-[var(--muted-soft)] transition-[border-color,box-shadow] focus:border-[var(--vermilion)] focus:ring-2 focus:ring-[rgba(181,51,42,.16)] disabled:cursor-not-allowed disabled:opacity-50", className)} {...props} />);
Textarea.displayName = "Textarea";

export { Textarea };
