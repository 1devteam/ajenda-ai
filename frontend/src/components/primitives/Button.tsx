import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "ghost" | "subtle" | "danger";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  children: ReactNode;
};

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-gradient-to-br from-crimson to-crimson-bright text-white shadow-[0_0_16px_rgba(179,18,43,0.2)] hover:brightness-110",
  ghost:
    "border border-os-border bg-transparent text-zinc-200 hover:border-zinc-500 hover:bg-os-surface-elevated",
  subtle:
    "bg-os-surface-elevated text-zinc-200 border border-os-border hover:border-zinc-500",
  danger:
    "bg-crimson/15 text-crimson-bright border border-crimson/40 hover:bg-crimson/25",
};

export default function Button({
  variant = "primary",
  className = "",
  children,
  type = "button",
  ...props
}: ButtonProps) {
  const base =
    "cc-focus-ring inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-[color,background-color,border-color,filter,transform] duration-150 ease-out active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100 motion-reduce:transition-none motion-reduce:active:scale-100 @md:min-h-10";

  return (
    <button type={type} className={`${base} ${VARIANTS[variant]} ${className}`.trim()} {...props}>
      {children}
    </button>
  );
}
