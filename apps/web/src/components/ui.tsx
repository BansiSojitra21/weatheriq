import type { ComponentProps } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-full text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-accent text-accent-foreground hover:opacity-90",
        secondary: "border border-border bg-white text-foreground hover:bg-muted",
        ghost: "hover:bg-muted",
        danger: "bg-danger text-white",
      },
      size: {
        default: "h-9 px-3",
        sm: "h-8 px-2.5 text-xs",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export function Card({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cn(
        "rounded-2xl border border-border bg-card shadow-[0_8px_24px_-18px_rgba(15,23,42,0.28)]",
        className,
      )}
      {...props}
    />
  );
}

export function Badge({
  className,
  tone = "neutral",
  ...props
}: ComponentProps<"span"> & { tone?: "neutral" | "accent" | "amber" | "danger" | "ok" }) {
  const tones = {
    neutral: "bg-muted text-foreground",
    accent: "bg-accent/10 text-accent",
    amber: "bg-amber/15 text-amber",
    danger: "bg-danger/15 text-danger",
    ok: "bg-ok/15 text-ok",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tones[tone], className)} {...props} />
  );
}

export function Input(props: ComponentProps<"input">) {
  return (
    <input
      {...props}
      className={cn(
        "h-10 w-full min-w-0 max-w-full rounded-xl border border-border bg-white px-3 text-sm text-foreground",
        props.className,
      )}
    />
  );
}

export function Select(props: ComponentProps<"select">) {
  return (
    <select
      {...props}
      className={cn("h-10 min-w-0 max-w-full rounded-xl border border-border bg-white px-3 text-sm text-foreground", props.className)}
    />
  );
}

export function Label(props: ComponentProps<"label">) {
  return <label {...props} className={cn("mb-1 block text-sm font-medium text-foreground", props.className)} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} />;
}
