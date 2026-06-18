import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Personalities() {
  return (
    <div>
      <PageHeader
        title="Personalities"
        description="Choose a preset persona or craft your own."
      />
      <ComingSoon feature="Personalities" iteration={4} />
    </div>
  );
}
