import { Button } from "@/components/ui";
import { Skeleton } from "@/components/ui";

export function StatePanel({
  status,
  message,
  onRetry,
}: {
  status: "loading" | "error" | "empty";
  message?: string;
  onRetry?: () => void;
}) {
  if (status === "loading") {
    return (
      <div role="status" aria-live="polite" className="grid gap-3">
        <span className="sr-only">Loading</span>
        <Skeleton className="h-28" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  return (
    <div role="status" className="rounded-xl border border-border bg-card p-6">
      <p className="text-sm text-muted-foreground">{message}</p>
      {status === "error" && onRetry ? (
        <Button className="mt-4" variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
