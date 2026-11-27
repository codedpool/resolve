import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ApprovalCard } from "../../src/components/ApprovalCard";
import { ApprovalList } from "../../src/components/ApprovalList";

function reply(status, payload) {
  return { ok: status < 400, status, json: async () => payload };
}

const imageApproval = { id: "a1", kind: "send_image_to_llm", status: "pending", payload: "e1" };
const evidence = [{ id: "e1", type: "document", vision_approval_id: "a1", sent_to_vision: false }];

let decisions;

beforeEach(() => {
  decisions = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path, options) => {
      if (path === "/approvals?case=c1") return reply(200, { approvals: [imageApproval] });
      if (path === "/cases/c1/evidence") return reply(200, { evidence });
      if (path === "/approvals/a1/decision") {
        decisions.push(JSON.parse(options.body));
        return reply(200, { id: "a1", status: "approved" });
      }
      return reply(404, { error: { code: "not_found", message: "Not found" } });
    }),
  );
  sessionStorage.setItem("evidence_names", JSON.stringify({ e1: "receipt-photo.jpg" }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});

it("names the image and says it goes to a vision model", () => {
  render(<ApprovalCard approval={imageApproval} evidence={evidence} names={{ e1: "receipt-photo.jpg" }} onDecide={vi.fn()} />);
  expect(screen.getByText("receipt-photo.jpg")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Send this image to a vision model?" })).toBeInTheDocument();
  expect(screen.getByText(/will be sent to a vision model/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send the image" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Do not send" })).toBeInTheDocument();
});

it("falls back to the file type and a short id when the name is unknown", () => {
  render(<ApprovalCard approval={imageApproval} evidence={evidence} names={{}} onDecide={vi.fn()} />);
  expect(screen.getByText("Your uploaded document (e1)")).toBeInTheDocument();
});

it("names the image in the list from the stored upload name", async () => {
  render(<ApprovalList caseId="c1" />);
  expect(await screen.findByText("receipt-photo.jpg")).toBeInTheDocument();
});

it("calls the API once when the button is double clicked", async () => {
  render(<ApprovalList caseId="c1" />);
  const approve = await screen.findByRole("button", { name: "Send the image" });
  fireEvent.click(approve);
  fireEvent.click(approve);
  expect(await screen.findByText("You approved this.")).toBeInTheDocument();
  expect(decisions).toEqual([{ decision: "approve" }]);
});

it("shows each approval kind with its own wording", () => {
  const kinds = [
    ["contact", "Use this contact for the company?"],
    ["summary", "Check the call summary"],
    ["disclosure", "The company asked for more details"],
  ];
  for (const [kind, title] of kinds) {
    const { unmount } = render(
      <ApprovalCard approval={{ id: kind, kind, status: "pending", payload: "{}" }} onDecide={vi.fn()} />,
    );
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    unmount();
  }
});

it("shows the error and allows another try when the decision fails", async () => {
  const onDecide = vi.fn().mockRejectedValueOnce(new Error("Wrong password")).mockResolvedValueOnce();
  render(<ApprovalCard approval={{ ...imageApproval, kind: "contact" }} onDecide={onDecide} />);
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Wrong password"));
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(onDecide).toHaveBeenCalledTimes(2));
});
