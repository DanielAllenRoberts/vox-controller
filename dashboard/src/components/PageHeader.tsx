import * as React from "react";
import { FadeIn } from "@/components/animate/FadeIn";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <FadeIn className="mb-6 flex items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-foreground-secondary">
            {description}
          </p>
        )}
      </div>
      {actions}
    </FadeIn>
  );
}
