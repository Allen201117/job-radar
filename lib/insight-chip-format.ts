export type InsightChipTone = "positive" | "warning" | "neutral";

export type InsightChip = {
  text: string;
  tone: InsightChipTone;
};

type HiringSignalPayload = {
  momentum?: unknown;
  intensity?: unknown;
};

const MOMENTUM_LABEL: Record<string, string> = {
  expanding: "扩张",
  steady: "平稳",
  tightening: "收紧",
};

const MOMENTUM_TONE: Record<string, InsightChipTone> = {
  expanding: "positive",
  steady: "neutral",
  tightening: "warning",
};

const INTENSITY_LABEL: Record<string, string> = {
  high: "高强度",
  mid: "中强度",
  low: "低强度",
};

export function formatHiringSignalChip(payload: HiringSignalPayload | null | undefined): InsightChip | null {
  const momentum = typeof payload?.momentum === "string" ? payload.momentum : "";
  const label = MOMENTUM_LABEL[momentum];
  if (!label) return null;

  const intensity = typeof payload?.intensity === "string" ? payload.intensity : "";
  const intensityLabel = INTENSITY_LABEL[intensity];
  return {
    text: intensityLabel ? `${label} · ${intensityLabel}` : label,
    tone: MOMENTUM_TONE[momentum] || "neutral",
  };
}

function formatUsdCompact(value: unknown): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}B 美元`;
  if (abs >= 1e6) return `${Math.round(value / 1e6)}M 美元`;
  return `${Math.round(value)} 美元`;
}

function formatEmployeeCompact(value: unknown): string | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return null;
  if (value >= 10000) {
    const wan = value / 10000;
    const text = Number.isInteger(wan) ? String(wan) : wan.toFixed(1).replace(/\.0$/, "");
    return `${text}万`;
  }
  return String(Math.round(value));
}

export function formatFinancialChips(financials: Record<string, unknown> | null | undefined): InsightChip[] {
  if (!financials || typeof financials !== "object") return [];

  const chips: InsightChip[] = [];
  if (typeof financials.fy === "number" || typeof financials.fy === "string") {
    const fy = String(financials.fy).trim();
    if (fy) chips.push({ text: `FY${fy}`, tone: "neutral" });
  }

  const revenue = formatUsdCompact(financials.revenue);
  if (revenue) chips.push({ text: `营收 ${revenue}`, tone: "positive" });

  const netIncome = formatUsdCompact(financials.net_income);
  if (netIncome) {
    const tone: InsightChipTone =
      typeof financials.net_income === "number" && financials.net_income < 0 ? "warning" : "positive";
    chips.push({ text: `净利 ${netIncome}`, tone });
  }

  if (typeof financials.revenue_yoy_pct === "number" && Number.isFinite(financials.revenue_yoy_pct)) {
    const yoy = Math.round(financials.revenue_yoy_pct);
    chips.push({ text: `同比 ${yoy >= 0 ? "+" : ""}${yoy}%`, tone: yoy >= 0 ? "positive" : "warning" });
  }

  const employees = formatEmployeeCompact(financials.employees);
  if (employees) chips.push({ text: `员工 ${employees}`, tone: "neutral" });

  return chips;
}
