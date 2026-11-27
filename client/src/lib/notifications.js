/** Inbox wording and the small event that keeps the nav count in step with the inbox. */

export const UNREAD_EVENT = "unread-count";

/** Tell the nav the new unread count. Pass null when the person signs out. */
export function announceUnread(count) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(UNREAD_EVENT, { detail: { count } }));
}

export function unreadCount(items) {
  return items.filter((item) => !item.read_at).length;
}

export function describe(item) {
  const payload = item.payload || {};
  if (item.kind === "approval_decided") {
    return payload.decision === "approve" ? "You approved a request." : "You said no to a request.";
  }
  if (item.kind === "deadline") {
    return "A deadline you were waiting on has arrived. Open your case to see what to do next.";
  }
  return "There is an update on your case.";
}
