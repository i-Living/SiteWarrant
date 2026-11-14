import { statusLabel, statusNote } from "../lib/format";

export function StatusStamp({ status }: { status: string }) {
  return (
    <span
      className="status-stamp"
      data-status={status}
      title={statusNote(status)}
    >
      <span className="status-dot" aria-hidden="true" />
      {statusLabel(status)}
    </span>
  );
}
