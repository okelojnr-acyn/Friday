interface AvatarProps {
  label: string;
  title?: string;
  size?: number;
}

/** Initials-only avatar -- no image upload/storage in Friday's MVP, so
 * this is the one consistent way a person shows up across apps (kanban
 * cards, list rows). */
export function Avatar({ label, title, size = 24 }: AvatarProps) {
  return (
    <span
      className="avatar"
      title={title ?? label}
      style={{ width: size, height: size, fontSize: size * 0.42 }}
    >
      {label}
    </span>
  );
}
