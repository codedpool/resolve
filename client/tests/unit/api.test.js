import { expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiError, createApi } from "../../src/lib/api";

function memory() {
  const bag = new Map();
  return {
    getItem: (key) => bag.get(key) ?? null,
    setItem: (key, value) => bag.set(key, value),
    removeItem: (key) => bag.delete(key),
  };
}

function jsonResponse(status, payload) {
  return {
    ok: status < 400,
    status,
    json: async () => payload,
  };
}

it("maps an error payload onto ApiError", async () => {
  const fetchImpl = vi.fn(async () => jsonResponse(401, { error: { code: "wrong_password", message: "Wrong password" } }));
  const api = createApi({ fetchImpl, storage: memory() });
  await expect(api.login({ email: "a@example.com", password: "nope" })).rejects.toMatchObject({
    name: "ApiError",
    status: 401,
    code: "wrong_password",
  });
  expect(ApiError).toBeTruthy();
});

it("retries a request once after step-up", async () => {
  const calls = [];
  const fetchImpl = vi.fn(async (path, options) => {
    calls.push(path);
    const body = options.body ? JSON.parse(options.body) : null;
    if (path === "/cases/1" && calls.filter((item) => item === "/cases/1").length === 1) {
      return jsonResponse(403, { error: { code: "step_up_required", message: "Enter your password again" } });
    }
    if (path === "/auth/step-up") {
      expect(body.password).toBe("correct-horse");
      return jsonResponse(200, { step_up_until: "2026-11-25T00:00:00Z" });
    }
    return jsonResponse(200, { id: "1", status: "deleted" });
  });
  const api = createApi({ fetchImpl, storage: memory() });
  api.setStepUp(async () => "correct-horse");
  const schema = z.object({ id: z.string(), status: z.string() });
  const result = await api.request("/cases/1", { method: "DELETE", schema });
  expect(result).toEqual({ id: "1", status: "deleted" });
  expect(calls).toEqual(["/cases/1", "/auth/step-up", "/cases/1"]);
});

it("keeps the access token in memory and the refresh token in session storage", async () => {
  const storage = memory();
  const fetchImpl = vi.fn(async () =>
    jsonResponse(201, { access_token: "access", refresh_token: "refresh", user_id: "u" }),
  );
  const api = createApi({ fetchImpl, storage });
  await api.signup({ email: "a@example.com", password: "correct-horse", language: "en" });
  expect(api.accessToken()).toBe("access");
  expect(api.refreshToken()).toBe("refresh");
  expect(storage.getItem("access_token")).toBeNull();
  api.logout();
  expect(api.accessToken()).toBeNull();
  expect(api.refreshToken()).toBeNull();
});
