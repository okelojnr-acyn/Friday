import type { ReactNode } from "react";

/** Each app's mark: one bold, solid shape in the tile's tint (owner's
 * brief, 27 Nov: flat geometric app marks, not thin outline icons; the
 * glass tile around it stays as it is). Drawn on a 48-unit grid so they
 * read at 18px in a rail and 30px on the home grid. Two-tone parts use
 * opacity, so every mark stays one colour (currentColor). */
const MARKS: Record<string, ReactNode> = {
  // My Store: a scalloped awning over a shopfront with its door.
  store: (
    <>
      <path d="M6 9H42V19A6 6 0 0 1 30 19A6 6 0 0 1 18 19A6 6 0 0 1 6 19Z" />
      <path d="M9 28H39V41H28V32H20V41H9Z" opacity={0.6} />
    </>
  ),
  // CRM & Sales: the pipeline narrowing to the deals you win.
  crm: (
    <>
      <rect x="5" y="8" width="38" height="8" rx="4" opacity={0.5} />
      <rect x="11" y="20" width="26" height="8" rx="4" opacity={0.72} />
      <rect x="18" y="32" width="12" height="8" rx="4" />
    </>
  ),
  // Invoicing: a bill with a torn edge.
  invoicing: (
    <path
      fillRule="evenodd"
      d="M10 5H38V43L33.33 39L28.67 43L24 39L19.33 43L14.67 39L10 43ZM16 13H32V17H16ZM16 21H27V25H16ZM16 29H30V33H16Z"
    />
  ),
  // Inventory: a box, three faces in three tones.
  inventory: (
    <>
      <path d="M24 5L41 14.5L24 24L7 14.5Z" opacity={0.5} />
      <path d="M7 16.5L23 25.5V43L7 34Z" />
      <path d="M25 25.5L41 16.5V34L25 43Z" opacity={0.72} />
    </>
  ),
  // Projects & Helpdesk: three board columns, work moving through.
  projects: (
    <>
      <rect x="6" y="7" width="10" height="34" rx="5" />
      <rect x="19" y="7" width="10" height="24" rx="5" opacity={0.72} />
      <rect x="32" y="7" width="10" height="15" rx="5" opacity={0.5} />
    </>
  ),
  // People: two people, one stepping up beside the other.
  minions: (
    <>
      <circle cx="33" cy="13" r="6" opacity={0.5} />
      <path d="M22 37A11 11 0 0 1 44 37Z" opacity={0.5} />
      <circle cx="18" cy="15" r="7.5" />
      <path d="M4 41A14 14 0 0 1 32 41Z" />
    </>
  ),
  // Accounting: the whole, with its share pulled out.
  accounting: (
    <>
      <path d="M21 27V9A18 18 0 1 0 39 27Z" />
      <path d="M25 23V5A18 18 0 0 1 43 23Z" opacity={0.55} />
    </>
  ),
  // Fleets: two chevrons, on the move.
  fleets: (
    <>
      <path d="M5 9H16L29 24L16 39H5L18 24Z" opacity={0.55} />
      <path d="M20 9H31L44 24L31 39H20L33 24Z" />
    </>
  ),
  // Web3: a block in the chain, its core held inside.
  web3: (
    <path
      fillRule="evenodd"
      d="M24 4L41.3 14V34L24 44L6.7 34V14ZM24 13.5L15 18.75V29.25L24 34.5L33 29.25V18.75ZM24 19.5A4.5 4.5 0 1 1 24 28.5A4.5 4.5 0 1 1 24 19.5Z"
    />
  ),
  // Point of Sale: the till, its receipt coming out.
  pos: (
    <>
      <path d="M15 5L18 3L21 5L24 3L27 5L30 3L33 5V14H15Z" opacity={0.55} />
      <path
        fillRule="evenodd"
        d="M14 16H34A5 5 0 0 1 39 21V38A5 5 0 0 1 34 43H14A5 5 0 0 1 9 38V21A5 5 0 0 1 14 16ZM15 21V28H33V21ZM17 32.5A2.25 2.25 0 1 0 17 37A2.25 2.25 0 1 0 17 32.5ZM24 32.5A2.25 2.25 0 1 0 24 37A2.25 2.25 0 1 0 24 32.5ZM31 32.5A2.25 2.25 0 1 0 31 37A2.25 2.25 0 1 0 31 32.5Z"
      />
    </>
  ),
  // Add apps: a plain, chunky plus.
  more: (
    <>
      <rect x="20" y="7" width="8" height="34" rx="4" />
      <rect x="7" y="20" width="34" height="8" rx="4" />
    </>
  ),
};

export const hasAppMark = (app: string) => app in MARKS;

export function AppMark({ app, size = 30 }: { app: string; size?: number }) {
  return (
    <svg viewBox="0 0 48 48" width={size} height={size} fill="currentColor" aria-hidden="true" focusable="false">
      {MARKS[app]}
    </svg>
  );
}
