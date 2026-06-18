import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Rules() {
  return (
    <div>
      <PageHeader
        title="Rules"
        description="Standing instructions the assistant always follows."
      />
      <ComingSoon feature="Rules" iteration={6} />
    </div>
  );
}
