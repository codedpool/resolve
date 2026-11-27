export function FactList({ facts }) {
  if (!facts.length) return <p>No facts yet.</p>;
  return (
    <ul className="fact-list">
      {facts.map((fact) => (
        <li key={fact.id}>
          <span>{fact.field}</span>
          <span>{fact.value}</span>
          <span className={`badge badge-${fact.certainty}`}>{fact.certainty}</span>
          <span>{fact.confirmation_state}</span>
        </li>
      ))}
    </ul>
  );
}
