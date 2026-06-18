import { Construction } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FadeIn } from "@/components/animate/FadeIn";

// Titled placeholder for pages built in later iterations, so routing works
// end-to-end now. `iteration` notes which round will deliver it.
export function ComingSoon({
  feature,
  iteration,
}: {
  feature: string;
  iteration: number;
}) {
  return (
    <FadeIn delay={0.05}>
      <Card
        glass
        className="flex flex-col items-center justify-center gap-4 px-6 py-20 text-center"
      >
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted text-foreground-muted">
          <Construction className="h-6 w-6" />
        </div>
        <div className="space-y-1">
          <p className="text-base font-medium">{feature} is coming soon</p>
          <p className="max-w-md text-sm text-foreground-secondary">
            This page is scaffolded so routing works end-to-end. It gets wired
            up in a later iteration of the dashboard build.
          </p>
        </div>
        <Badge variant="accent">Iteration {iteration}</Badge>
      </Card>
    </FadeIn>
  );
}
