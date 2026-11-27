export const CRITICAL_FIELDS = ["company_name", "order_id", "amount", "order_date", "promised_date", "desired_remedy"];

export function applyCorrection(facts, previous, created, value) {
  return facts.map((fact) =>
    fact.field === previous.field
      ? {
          ...fact,
          id: created.id,
          value,
          version: created.version,
          confirmation_state: created.confirmation_state,
        }
      : fact,
  );
}
