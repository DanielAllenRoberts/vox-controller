import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function TokenUsage() {
  return (
    <div>
      <PageHeader
        title="Token Usage"
        description="Live token usage, cost, and per-model breakdown."
      />
      <ComingSoon feature="Token usage & cost" iteration={2} />
    </div>
  );
}
