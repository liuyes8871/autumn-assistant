import * as React from "react";
import { Slot } from "radix-ui";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-[7px] text-sm font-semibold outline-none transition-[background-color,border-color,color,transform,box-shadow] duration-150 focus-visible:ring-2 focus-visible:ring-[rgba(181,51,42,.36)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-45 active:scale-[.98]",
  {
    variants: {
      variant: {
        ink: "bg-[var(--ink)] text-white hover:bg-[var(--ink-soft)]",
        vermilion: "bg-[var(--vermilion)] text-white hover:bg-[var(--vermilion-deep)]",
        outline: "border border-[var(--line-strong)] bg-white text-[var(--ink)] hover:border-[var(--ink)] hover:bg-[var(--paper-muted)]",
        ghost: "text-[var(--ink-soft)] hover:bg-[var(--paper-muted)] hover:text-[var(--ink)]",
        link: "rounded-none text-[var(--vermilion)] underline-offset-4 hover:underline",
      },
      size: {
        default: "min-h-11 px-4 py-2",
        sm: "min-h-9 px-3 text-[13px]",
        lg: "min-h-12 px-5 text-base",
        icon: "size-10",
      },
    },
    defaultVariants: { variant: "ink", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot.Root : "button";
    return <Comp ref={ref} className={cn(buttonVariants({ variant, size, className }))} {...props} />;
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
