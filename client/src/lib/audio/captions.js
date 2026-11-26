/**
 * Folds a caption message into the list shown on screen. A caption that is not final is a live
 * guess that the next caption from the same speaker replaces. The text is already redacted by the server.
 */
export function applyCaption(list, caption, nextId) {
  const who = caption.who === "agent" ? "agent" : "user";
  const text = typeof caption.text === "string" ? caption.text : "";
  const final = caption.final !== false;
  const last = list[list.length - 1];

  if (last && last.who === who && !last.final) {
    return text.trim() ? [...list.slice(0, -1), { ...last, text, final }] : list.slice(0, -1);
  }
  if (!text.trim()) return list;
  return [...list, { id: nextId, who, text, final }];
}
