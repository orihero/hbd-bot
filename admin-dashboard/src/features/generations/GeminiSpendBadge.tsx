import { Sparkles } from "lucide-react";
import type { JSX } from "react";

import type { GeminiSpendResponse } from "@/api/dashboard";
import { Badge, type BadgeTone } from "@/components/Badge";
import { useGeminiSpend } from "@/features/dashboard/useDashboardData";

export const GEMINI_OUT_OF_CREDIT =
  "Gemini out of credit — renders fail over to ElevenLabs. Top up in AI Studio.";

export function formatUsdPlain(v: number): string {
  return `$${v.toFixed(2)}`;
}

interface SpendReading {
  readonly label: string;
  readonly tone: BadgeTone;
  readonly title: string | undefined;
}

/**
 * The badge's words and tone. Read-only: Google exposes no balance API, so what this shows is
 * our own metered SPEND at a flat per-request price — an estimate, and labelled one. Depleted
 * (the latest call was refused for lack of prepay credit) outranks the figure.
 */
export function readSpend(spend: GeminiSpendResponse | undefined): SpendReading {
  if (spend === undefined) {
    return { label: "Gemini this month: …", tone: "muted", title: undefined };
  }
  const detail =
    `today ${formatUsdPlain(spend.today.spentUsd)} · ` +
    `${String(spend.monthToDate.pricedCalls)} songs this month · ` +
    "estimated at our per-request price";
  if (spend.isDepleted) {
    return { label: GEMINI_OUT_OF_CREDIT, tone: "danger", title: detail };
  }
  return {
    label: `Gemini this month ≈ ${formatUsdPlain(spend.monthToDate.spentUsd)} (est.)`,
    tone: "neutral",
    title: detail,
  };
}

export function GeminiSpendBadge(): JSX.Element | null {
  const { data, error } = useGeminiSpend();
  // A role or a deployment that cannot read the figure gets no badge rather than a fault line
  // in the Generations toolbar; the Finances card is where a failed read is reported.
  if (error !== null && data === undefined) return null;
  const reading = readSpend(data);
  return (
    <Badge
      tone={reading.tone}
      title={reading.title}
      icon={<Sparkles className="h-3 w-3" strokeWidth={2} />}
    >
      {reading.label}
    </Badge>
  );
}
