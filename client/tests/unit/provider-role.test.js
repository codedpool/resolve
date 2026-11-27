import { describe, expect, it, vi } from "vitest";

import { restCalls } from "@/lib/audio/voiceClient";

describe("the call role", () => {
  it("asks for a consumer call unless told otherwise", async () => {
    const request = vi.fn().mockResolvedValue({});
    await restCalls({ request }).requestCall("case-1");
    expect(request.mock.calls[0][1].body).toEqual({ case_id: "case-1", role: "consumer" });
  });

  it("asks for a provider call when you play the company", async () => {
    const request = vi.fn().mockResolvedValue({});
    await restCalls({ request }, "provider_human").requestCall("case-1");
    expect(request.mock.calls[0][1].body).toEqual({ case_id: "case-1", role: "provider_human" });
  });
});
