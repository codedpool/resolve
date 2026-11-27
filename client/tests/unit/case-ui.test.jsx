import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { FactList } from "../../src/components/FactList";
import { StatusBadge } from "../../src/components/StatusBadge";

it("shows simulated resolution beside the status", () => {
  render(<StatusBadge status="intake" simulated />);
  expect(screen.getByText("intake")).toBeInTheDocument();
  expect(screen.getByText("Simulated resolution")).toBeInTheDocument();
});

it("hides the simulated label when the case is not simulated", () => {
  render(<StatusBadge status="intake" simulated={false} />);
  expect(screen.queryByText("Simulated resolution")).not.toBeInTheDocument();
});

it("shows a certainty badge and the stored value", () => {
  render(
    <FactList
      facts={[
        {
          id: "1",
          field: "amount",
          value: "around 1200",
          certainty: "approximate",
          confirmation_state: "unconfirmed",
        },
      ]}
    />,
  );
  expect(screen.getByText("around 1200")).toBeInTheDocument();
  expect(screen.getByText("approximate")).toBeInTheDocument();
  expect(screen.getByText("unconfirmed")).toBeInTheDocument();
});
