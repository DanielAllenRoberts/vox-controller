import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Memory() {
  return (
    <div>
      <PageHeader
        title="Memory"
        description="What Vox remembers — add, recall, and prune."
      />
      <ComingSoon feature="Memory" iteration={6} />
    </div>
  );
}
