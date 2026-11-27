/** Browser API client. The access token stays in memory. The refresh token stays in session storage. */

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function createApi({ fetchImpl, storage } = {}) {
  const memory = storage || defaultStorage();
  let accessToken = null;
  let stepUp = null;

  async function send(path, method, body) {
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    const root = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
    const response = await (fetchImpl || globalThis.fetch)(`${root}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    return { response, payload };
  }

  function fail(response, payload) {
    const error = payload.error || {};
    throw new ApiError(response.status, error.code || "request_failed", error.message || "Request failed");
  }

  async function request(path, { method = "GET", body, schema } = {}) {
    let { response, payload } = await send(path, method, body);
    if (response.status === 403 && payload.error?.code === "step_up_required" && stepUp) {
      const password = await stepUp();
      const stepped = await send("/auth/step-up", "POST", { password });
      if (!stepped.response.ok) fail(stepped.response, stepped.payload);
      ({ response, payload } = await send(path, method, body));
    }
    if (!response.ok) fail(response, payload);
    return schema ? schema.parse(payload) : payload;
  }

  return {
    setStepUp(handler) {
      stepUp = handler;
    },
    accessToken() {
      return accessToken;
    },
    refreshToken() {
      return memory.getItem("refresh_token");
    },
    async signup(body) {
      const payload = await request("/auth/signup", { method: "POST", body });
      remember(payload);
      return payload;
    },
    async login(body) {
      const payload = await request("/auth/login", { method: "POST", body });
      remember(payload);
      return payload;
    },
    logout() {
      accessToken = null;
      memory.removeItem("refresh_token");
    },
    request,
    async upload(path, file) {
      const form = new FormData();
      form.append("file", file);
      form.append("type", "document");
      const headers = {};
      if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
      const root = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
      const response = await (fetchImpl || globalThis.fetch)(`${root}${path}`, { method: "POST", headers, body: form });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) fail(response, payload);
      return payload;
    },
  };

  function remember(payload) {
    accessToken = payload.access_token || null;
    if (payload.refresh_token) memory.setItem("refresh_token", payload.refresh_token);
  }
}

function defaultStorage() {
  if (typeof sessionStorage !== "undefined") return sessionStorage;
  const bag = new Map();
  return {
    getItem: (key) => bag.get(key) ?? null,
    setItem: (key, value) => bag.set(key, value),
    removeItem: (key) => bag.delete(key),
  };
}
