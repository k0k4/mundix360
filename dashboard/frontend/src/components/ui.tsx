import React from "react";
import { Card } from "antd";
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  MinusOutlined,
} from "@ant-design/icons";

/* ---- List header title (for Refine <List>) ------------------------------ */
export function ListTitle({
  eyebrow,
  children,
}: {
  eyebrow?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 2 }}>
      {eyebrow && <span className="mx-eyebrow">{eyebrow}</span>}
      <span className="mx-page-title" style={{ fontSize: 20 }}>
        {children}
      </span>
    </span>
  );
}

/* ---- Page header --------------------------------------------------------- */
export function PageHeader({
  eyebrow,
  title,
  subtitle,
  extra,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  extra?: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        gap: 16,
        marginBottom: 20,
        flexWrap: "wrap",
      }}
    >
      <div>
        {eyebrow && (
          <div className="mx-eyebrow" style={{ marginBottom: 8 }}>
            {eyebrow}
          </div>
        )}
        <h1 className="mx-page-title">{title}</h1>
        {subtitle && (
          <div className="mx-page-sub" style={{ marginTop: 4 }}>
            {subtitle}
          </div>
        )}
      </div>
      {extra && <div>{extra}</div>}
    </div>
  );
}

/* ---- Tiny inline sparkline (no deps) ------------------------------------- */
export function Sparkline({
  data,
  color = "#22d3ee",
  width = 96,
  height = 32,
}: {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  if (!data || data.length < 2) {
    return <div style={{ width, height }} />;
  }
  const max = Math.max(...data);
  const min = Math.min(...data);
  const span = max - min || 1;
  const stepX = width / (data.length - 1);
  const pts = data.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / span) * (height - 4) - 2;
    return [x, y] as const;
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area =
    `0,${height} ` + line + ` ${width},${height}`;
  const gid = React.useId();
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.35} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gid})`} />
      <polyline
        points={line}
        fill="none"
        stroke={color}
        strokeWidth={1.8}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

/* ---- Trend badge --------------------------------------------------------- */
export function TrendBadge({ delta }: { delta?: number }) {
  if (delta === undefined || delta === null || Number.isNaN(delta)) return null;
  const dir = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const Icon =
    dir === "up" ? ArrowUpOutlined : dir === "down" ? ArrowDownOutlined : MinusOutlined;
  return (
    <span className={`mx-trend ${dir}`}>
      <Icon style={{ fontSize: 10 }} />
      {Math.abs(delta)}%
    </span>
  );
}

/* ---- KPI card ------------------------------------------------------------ */
export function KpiCard({
  icon,
  color,
  label,
  value,
  suffix,
  spark,
  delta,
}: {
  icon: React.ReactNode;
  color: string;
  label: string;
  value: number | string;
  suffix?: string;
  spark?: number[];
  delta?: number;
}) {
  return (
    <Card
      hoverable
      bordered={false}
      className="mx-kpi"
      style={{ ["--mx-kpi-accent" as any]: `${color}22` }}
      styles={{ body: { padding: 18 } }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div
          className="mx-kpi-icon"
          style={{ background: `${color}1f`, color }}
        >
          {icon}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="mx-kpi-label">{label}</div>
          <div className="mx-kpi-value">
            {value}
            {suffix && (
              <span
                style={{
                  fontSize: 14,
                  color: "var(--mx-text-dim)",
                  marginLeft: 4,
                  fontWeight: 500,
                }}
              >
                {suffix}
              </span>
            )}
          </div>
        </div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-end",
            gap: 6,
          }}
        >
          {delta !== undefined && <TrendBadge delta={delta} />}
          {spark && <Sparkline data={spark} color={color} />}
        </div>
      </div>
    </Card>
  );
}
