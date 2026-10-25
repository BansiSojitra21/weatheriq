import { Button } from "@/components/ui";

export function AlertActions({
  status,
  onChange,
}: {
  status: string;
  onChange: (status: "acknowledged" | "resolved") => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button type="button" variant="secondary" size="sm" disabled={status !== "open"} onClick={() => onChange("acknowledged")}>
        Acknowledge
      </Button>
      <Button type="button" variant="secondary" size="sm" disabled={status === "resolved"} onClick={() => onChange("resolved")}>
        Resolve
      </Button>
    </div>
  );
}
