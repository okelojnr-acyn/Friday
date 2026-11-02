import type { HTMLAttributes } from "react";

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={["card", "card-padded", className].filter(Boolean).join(" ")} {...rest} />;
}
