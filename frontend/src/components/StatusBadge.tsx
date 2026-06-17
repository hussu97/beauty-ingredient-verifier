import clsx from "clsx";
import type { ReactNode } from "react";

type Props = {
  children: ReactNode;
  tone?: "neutral" | "good" | "warn" | "danger";
};

export default function StatusBadge({ children, tone = "neutral" }: Props) {
  return <span className={clsx("status-badge", `tone-${tone}`)}>{children}</span>;
}
