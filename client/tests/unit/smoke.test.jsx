import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { z } from "zod";

function Mark() {
  return <span>SIMULATED</span>;
}

const healthSchema = z.object({ ok: z.boolean() });

it("validates a payload with zod", () => {
  expect(healthSchema.parse({ ok: true })).toEqual({ ok: true });
});

it("renders a label", () => {
  render(<Mark />);
  expect(screen.getByText("SIMULATED")).toBeInTheDocument();
});
