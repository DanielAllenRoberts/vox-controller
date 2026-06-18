import { PageHeader } from "@/components/PageHeader";
import { ComingSoon } from "@/components/ComingSoon";

export function Settings() {
  return (
    <div>
      <PageHeader
        title="Settings"
        description="Brains, behavior, voice, and debug toggles."
      />
      <ComingSoon feature="Settings" iteration={3} />
    </div>
  );
}
