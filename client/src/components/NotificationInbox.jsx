"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/components/StepUpDialog";
import { announceUnread, describe, unreadCount } from "@/lib/notifications";

export function NotificationInbox({ send = (path, options) => api.request(path, options) }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const marking = useRef(new Set());

  useEffect(() => {
    let live = true;
    send("/notifications")
      .then((payload) => {
        if (!live) return;
        // The server lists oldest first. People want the newest on top.
        const list = [...payload.notifications].reverse();
        setItems(list);
        announceUnread(unreadCount(list));
      })
      .catch((err) => {
        if (!live) return;
        setItems([]);
        setError(`Could not load your messages. ${err.message}. Refresh the page to try again.`);
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function markRead(item) {
    if (marking.current.has(item.id)) return;
    marking.current.add(item.id);
    setError("");
    try {
      const saved = await send(`/notifications/${item.id}/read`, { method: "POST" });
      setItems((current) => {
        const next = current.map((entry) => (entry.id === item.id ? { ...entry, read_at: saved.read_at } : entry));
        announceUnread(unreadCount(next));
        return next;
      });
    } catch (err) {
      marking.current.delete(item.id);
      setError(`Could not mark that message as read. ${err.message}. Try again.`);
    }
  }

  if (!items) return <p>Loading your messages.</p>;

  const unread = unreadCount(items);

  return (
    <section className="stack" aria-labelledby="inbox-title">
      <h1 id="inbox-title">Messages</h1>
      <p role="status">{unread === 0 ? "You have no unread messages." : `${unread} unread ${unread === 1 ? "message" : "messages"}.`}</p>
      {error ? (
        <p role="alert" className="form-error">
          {error}
        </p>
      ) : null}
      {items.length === 0 && !error ? <p>No messages yet. Updates on your cases will show up here.</p> : null}
      <ul className="inbox">
        {items.map((item) => (
          <li key={item.id} className={item.read_at ? "card read" : "card unread"}>
            <p>
              {item.read_at ? null : <span className="unread-mark">New. </span>}
              {describe(item)}
            </p>
            {item.read_at ? null : (
              <button type="button" className="quiet" onClick={() => markRead(item)}>
                Mark as read
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
