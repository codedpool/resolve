export function Timeline({ events }) {
  if (!events.length) return <p>No events yet.</p>;
  return (
    <ol>
      {events.map((event) => (
        <li key={event.id}>{event.kind}</li>
      ))}
    </ol>
  );
}
