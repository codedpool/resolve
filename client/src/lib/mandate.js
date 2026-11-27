/** Choices and wording for the mandate card. The server stores the values; this file only names them. */

export const DISCLOSURE_FIELDS = [
  { key: "order_id", label: "Order number", on: true },
  { key: "amount", label: "Amount you paid", on: true },
  { key: "order_date", label: "Order date", on: true },
  { key: "issue_summary", label: "What went wrong", on: true },
  { key: "consumer_name", label: "Your name", on: true },
  { key: "consumer_phone", label: "Your phone number", on: false },
  { key: "consumer_address", label: "Your address", on: false },
  { key: "consumer_email", label: "Your email address", on: false },
];

export const DEFAULT_DISCLOSURE = DISCLOSURE_FIELDS.filter((field) => field.on).map((field) => field.key);

export const GOALS = [
  { value: "refund", label: "A full refund" },
  { value: "replacement", label: "A replacement" },
  { value: "repair", label: "A repair" },
];

export const CALL_LIMITS = [
  { seconds: 300, label: "5 minutes" },
  { seconds: 600, label: "10 minutes" },
  { seconds: 900, label: "15 minutes" },
  { seconds: 1200, label: "20 minutes" },
];

export const EXPIRY_CHOICES = [
  { days: 7, label: "7 days" },
  { days: 14, label: "14 days" },
  { days: 30, label: "30 days" },
];

export const BOUNDARIES = [
  "It will not accept a part payment or ask you to give up any right. It tells you about the offer and you decide.",
  "It will say at the start that it is an AI assistant calling for you.",
  "It will never share an OTP, a password or a card number, whatever you choose here.",
];

export const NEVER_SHARED = "Anything not ticked above stays private.";

export function newDraft() {
  return { goal: "refund", disclosure: [...DEFAULT_DISCLOSURE], callLimitSeconds: 600, expiresInDays: 30 };
}

export function draftFromMandate(mandate) {
  if (!mandate) return newDraft();
  return {
    goal: mandate.goal,
    disclosure: [...mandate.disclosure],
    callLimitSeconds: mandate.call_limit_seconds,
    expiresInDays: 30,
  };
}

export function mandateBody(draft) {
  return {
    action: "grant",
    goal: draft.goal,
    disclosure: DISCLOSURE_FIELDS.filter((field) => draft.disclosure.includes(field.key)).map((field) => field.key),
    allowed_actions: ["ask_for_refund"],
    limits: { accept_partial: false },
    channels: ["simulated_call"],
    call_limit_seconds: draft.callLimitSeconds,
    expires_in_days: draft.expiresInDays,
  };
}

export function labelFor(key) {
  return DISCLOSURE_FIELDS.find((field) => field.key === key)?.label || key.replace(/_/g, " ");
}

export function goalLabel(value) {
  return GOALS.find((goal) => goal.value === value)?.label || value;
}

export function minutesLabel(seconds) {
  const minutes = Math.round(seconds / 60);
  return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
}

export function formatDate(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
}

/** One entry per field the person must confirm before saving. */
export function readBack(draft) {
  const shared = DISCLOSURE_FIELDS.filter((field) => draft.disclosure.includes(field.key)).map((field) => field.label);
  const kept = DISCLOSURE_FIELDS.filter((field) => !draft.disclosure.includes(field.key)).map((field) => field.label);
  return [
    { key: "goal", title: "What you want", text: `You want ${goalLabel(draft.goal).toLowerCase()}.` },
    {
      key: "disclosure",
      title: "What it may share",
      text: shared.length ? `It may share: ${shared.join(", ")}.` : "It may not share any details.",
      note: kept.length ? `It will keep private: ${kept.join(", ")}.` : "",
    },
    { key: "boundaries", title: "What it will not do", text: BOUNDARIES.join(" ") },
    { key: "limit", title: "Call length", text: `Each call stops after ${minutesLabel(draft.callLimitSeconds)}.` },
    {
      key: "expiry",
      title: "When it ends",
      text: `This permission ends in ${draft.expiresInDays} days. You can cancel it earlier.`,
    },
  ];
}
