import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { NotificationInbox } from "../../src/components/NotificationInbox";
import { SiteNav } from "../../src/components/SiteNav";
import { announceUnread } from "../../src/lib/notifications";

vi.mock("next/navigation", () => ({ usePathname: () => "/inbox" }));
vi.mock("next/link", () => ({ default: ({ href, children, ...rest }) => <a href={href} {...rest}>{children}</a> }));

function reply(status, payload) {
  return { ok: status < 400, status, json: async () => payload };
}

const items = [
  { id: "n1", kind: "approval_decided", payload: { decision: "approve" }, read_at: null },
  { id: "n2", kind: "deadline", payload: {}, read_at: null },
  { id: "n3", kind: "approval_decided", payload: { decision: "reject" }, read_at: "2026-11-26T00:00:00Z" },
];

let reads;

beforeEach(() => {
  reads = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path) => {
      if (path === "/notifications") return reply(200, { notifications: items });
      const match = path.match(/^\/notifications\/(.+)\/read$/);
      if (match) {
        reads.push(match[1]);
        return reply(200, { id: match[1], read_at: "2026-11-27T00:00:00Z" });
      }
      return reply(404, { error: { code: "not_found", message: "Not found" } });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("lists messages, newest first, with the unread count", async () => {
  render(<NotificationInbox />);
  expect(await screen.findByText("2 unread messages.")).toBeInTheDocument();
  const rows = screen.getAllByRole("listitem");
  expect(rows).toHaveLength(3);
  expect(rows[0]).toHaveTextContent("You said no to a request.");
});

it("marks a message read once and lowers the count", async () => {
  render(<NotificationInbox />);
  await screen.findByText("2 unread messages.");
  const [first] = screen.getAllByRole("button", { name: "Mark as read" });
  fireEvent.click(first);
  fireEvent.click(first);
  expect(await screen.findByText("1 unread message.")).toBeInTheDocument();
  expect(reads).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: "Mark as read" })).toHaveLength(1);
});

it("keeps the unread count in the nav in step with the inbox", async () => {
  render(
    <>
      <SiteNav />
      <NotificationInbox />
    </>,
  );
  await screen.findByText("2 unread messages.");
  expect(await screen.findByLabelText("2 unread")).toBeInTheDocument();
  await act(async () => {
    fireEvent.click(screen.getAllByRole("button", { name: "Mark as read" })[0]);
  });
  expect(await screen.findByLabelText("1 unread")).toBeInTheDocument();
  act(() => announceUnread(null));
  expect(screen.queryByRole("link", { name: /Messages/ })).not.toBeInTheDocument();
});
