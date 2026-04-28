import type { DonutSlice } from "./dashboard-data";

/**
 * Tiny SVG donut chart. Pure function of its input. Not pulled from any
 * chart library — it's one loop and two <circle>s. If the needs grow
 * (animation, tooltips, click-to-filter) swap this for Recharts
 * <PieChart>.
 */
export function Donut({
  data,
  total,
  size = 140,
  radius = 54,
  strokeWidth = 14,
}: {
  data: DonutSlice[];
  total: number;
  size?: number;
  radius?: number;
  strokeWidth?: number;
}) {
  const circumference = 2 * Math.PI * radius;
  let offset = 0;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {/* Track */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="hsl(var(--muted))"
        strokeWidth={strokeWidth}
      />
      {/* Slices */}
      {data.map((d, i) => {
        const pct = total > 0 ? d.count / total : 0;
        const dash = pct * circumference;
        const el = (
          <circle
            key={i}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={d.color}
            strokeWidth={strokeWidth}
            strokeDasharray={`${dash} ${circumference - dash}`}
            strokeDashoffset={-offset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        );
        offset += dash;
        return el;
      })}
      {/* Center label */}
      <text
        x="50%"
        y="48%"
        textAnchor="middle"
        className="fill-foreground"
        style={{ fontSize: 22, fontWeight: 600 }}
      >
        {total}
      </text>
      <text
        x="50%"
        y="62%"
        textAnchor="middle"
        className="fill-muted-foreground"
        style={{ fontSize: 10, letterSpacing: 0.5 }}
      >
        ALERTS
      </text>
    </svg>
  );
}
