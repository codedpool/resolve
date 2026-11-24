export function StatusBadge({ status, simulated }) {
  return (
    <p className="status-line">
      <span>{status}</span>
      {simulated ? <span className="simulated">Simulated resolution</span> : null}
    </p>
  );
}
