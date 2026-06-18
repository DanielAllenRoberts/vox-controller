import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function AxTree() {
  return (
    <div>
      <PageHeader
        title="AX Tree"
        description="Read-only accessibility tree of the focused app."
      />
      <ComingSoon feature="AX tree visualization" iteration={5} />
    </div>
  );
}
