import { Component, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { Button } from "./Button";

interface State {
  error: Error | null;
}

class Boundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("A page failed to show", error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page" role="alert">
        <h1 className="page-title">This page didn't load</h1>
        <p className="field-label">Something on it went wrong. The rest of Friday still works: pick another page, or try again.</p>
        <Button variant="primary" onClick={() => window.location.reload()}>
          Try again
        </Button>
      </div>
    );
  }
}

/** One page throwing never blanks the whole app (2026-11-26: Purchase
 * orders to Products did): that page says so, the menus stay, and moving
 * to another page starts it fresh. */
export function PageErrorBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return <Boundary key={pathname}>{children}</Boundary>;
}
