export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api/proxy/${path.replace(/^\//, "")}`, {
    ...init,
    headers,
    cache: "no-store",
  });
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as { error?: { message?: string } }) : null;
  if (!response.ok) {
    throw new ApiError(payload?.error?.message || `Request failed (${response.status})`, response.status);
  }
  return payload as T;
}
