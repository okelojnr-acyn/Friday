/** A semicircle dial, 0-100 -- the hero-metric visualization. Pure SVG
 * (no charting library) so it re-themes with the token system like
 * everything else in the kit: the track reads --border, the fill and
 * needle read --accent/--text. */
interface GaugeProps {
  percent: number;
  size?: number;
}

const R = 80;
const CX = 100;
const CY = 100;
const ARC_LENGTH = Math.PI * R;

export function Gauge({ percent, size = 108 }: GaugeProps) {
  const clamped = Math.max(0, Math.min(100, percent));
  const dashoffset = ARC_LENGTH * (1 - clamped / 100);
  const angleRad = ((180 - (clamped / 100) * 180) * Math.PI) / 180;
  const needleLen = R - 16;
  const nx = CX + needleLen * Math.cos(angleRad);
  const ny = CY - needleLen * Math.sin(angleRad);
  const arcPath = `M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`;

  return (
    <svg width={size} height={(size * 110) / 200} viewBox="0 0 200 110" fill="none">
      <path d={arcPath} stroke="var(--border)" strokeWidth={10} strokeLinecap="round" />
      <path
        d={arcPath}
        stroke="var(--accent)"
        strokeWidth={10}
        strokeLinecap="round"
        strokeDasharray={`${ARC_LENGTH} ${ARC_LENGTH}`}
        strokeDashoffset={dashoffset}
      />
      <line x1={CX} y1={CY} x2={nx} y2={ny} stroke="var(--text)" strokeWidth={3} strokeLinecap="round" />
      <circle cx={CX} cy={CY} r={5} fill="var(--text)" />
    </svg>
  );
}
