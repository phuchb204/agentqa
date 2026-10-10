export function formatCost(
  costState: string,
  costTotal: string | null,
  currency: string | null,
): string {
  if (costState === "unknown" || costTotal === null) {
    return "Không có dữ liệu chi phí";
  }
  const amount = [costTotal, currency ?? ""].join(" ").trim();
  if (costState === "partial") {
    return `${amount} (partial)`;
  }
  return amount;
}

export function formatUsage(usage: {
  state: string;
  input_tokens: number;
  output_tokens: number;
  unknown_calls: number;
}): string {
  if (usage.state === "unknown") {
    return "Không có dữ liệu usage";
  }
  const suffix = usage.unknown_calls > 0 ? ` · ${usage.unknown_calls} call unknown` : "";
  return `${usage.input_tokens} input / ${usage.output_tokens} output${suffix}`;
}

export function verdictLabel(verdict: string | null, terminal: boolean): string {
  if (!terminal || verdict === null) {
    return "Chưa có kết luận";
  }
  switch (verdict) {
    case "passed":
      return "Đạt";
    case "failed":
      return "Không đạt";
    default:
      return "Chưa đủ căn cứ (inconclusive)";
  }
}
