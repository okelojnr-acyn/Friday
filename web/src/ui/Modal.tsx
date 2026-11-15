import type { ReactNode } from "react";
import { Button } from "./Button";
import { Icon } from "./Icon";

interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** A roomier modal, for editors with a photo beside the fields. */
  wide?: boolean;
}

export function Modal({ title, onClose, children, footer, wide }: ModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className={`modal${wide ? " modal-wide" : ""}`} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <Icon name="close" size={16} />
          </Button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-footer">{footer}</div> : null}
      </div>
    </div>
  );
}
