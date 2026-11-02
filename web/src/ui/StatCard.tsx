import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon, type IconName } from "./Icon";

interface StatCardProps {
  to?: string;
  icon: IconName;
  label: string;
  value: string;
  featured?: boolean;
  footer?: ReactNode;
}

/** The dashboard's recurring card shape: an icon chip, an arrow-button
 * that doubles as "open the full list", a big number, and a footer
 * that's free to be a short label, a dot-progress row, or nothing --
 * see DashboardPage.tsx for how each metric picks its footer. */
export function StatCard({ to, icon, label, value, featured, footer }: StatCardProps) {
  const className = ["stat-card", featured ? "stat-card-featured" : ""].filter(Boolean).join(" ");
  const content = (
    <>
      <div className="stat-card-head">
        <span className="stat-icon-chip">
          <Icon name={icon} size={12} />
        </span>
        <span className="stat-arrow-btn">
          <Icon name="arrow-up-right" size={11} />
        </span>
      </div>
      <div className="stat-card-body">
        <span className="stat-label">{label}</span>
        <span className="stat-value">{value}</span>
      </div>
      <div className="stat-card-foot">{footer}</div>
    </>
  );
  if (to) {
    return (
      <Link to={to} className={className}>
        {content}
      </Link>
    );
  }
  return <div className={className}>{content}</div>;
}
