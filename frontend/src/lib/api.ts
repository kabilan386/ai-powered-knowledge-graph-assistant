import type {
  GraphRAGRequest,
  GraphRAGResponse,
  GraphResponse,
  UploadResponse,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status = 0,
    public readonly code = "network_error",
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export function apiBaseUrl(): string {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (!value)
    throw new ApiError(
      "Set NEXT_PUBLIC_API_BASE_URL in frontend/.env.local and restart the frontend.",
      0,
      "configuration_error",
    );
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ApiError(
      "The backend URL must be an absolute HTTP or HTTPS URL.",
      0,
      "configuration_error",
    );
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    throw new ApiError(
      "The backend URL must be an HTTP or HTTPS URL without credentials, query, or fragment.",
      0,
      "configuration_error",
    );
  return value.replace(/\/+$/, "");
}
function messageFor(body: unknown, status: number): ApiError {
  if (typeof body === "object" && body !== null && "error" in body) {
    const error = body.error;
    if (
      typeof error === "object" &&
      error !== null &&
      "message" in error &&
      typeof error.message === "string"
    ) {
      return new ApiError(
        error.message,
        status,
        "code" in error && typeof error.code === "string"
          ? error.code
          : "api_error",
      );
    }
  }
  return new ApiError(
    status === 422
      ? "The request was rejected. Check your input and try again."
      : `The backend request failed (${status}). Please try again.`,
    status,
    "api_error",
  );
}
async function request<T>(
  path: string,
  init: RequestInit,
  timeout: number,
  signal?: AbortSignal,
): Promise<T> {
  const url = `${apiBaseUrl()}${path}`;
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, timeout);
  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
      cache: "no-store",
    });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) throw messageFor(body, response.status);
    if (typeof body !== "object" || body === null)
      throw new ApiError(
        "The backend returned an invalid response.",
        response.status,
        "invalid_response",
      );
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal?.aborted)
      throw new DOMException("Request cancelled", "AbortError");
    throw new ApiError(
      controller.signal.aborted
        ? "The request timed out. Check the backend before trying again."
        : "Cannot reach the backend. Check that it is running and CORS allows this frontend.",
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
export const api = {
  ask: (body: GraphRAGRequest, signal?: AbortSignal) =>
    request<GraphRAGResponse>(
      "/api/graphrag/ask",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
      150_000,
      signal,
    ),
  graph: (signal?: AbortSignal) =>
    request<GraphResponse>("/api/graph", { method: "GET" }, 20_000, signal),
  upload(
    file: File,
    onStage: (stage: "uploading" | "processing") => void,
    signal?: AbortSignal,
  ): Promise<UploadResponse> {
    const url = `${apiBaseUrl()}/api/documents/upload`;
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      xhr.timeout = 300_000;
      const abort = () => xhr.abort();
      const cleanup = () => signal?.removeEventListener("abort", abort);
      xhr.upload.onload = () => onStage("processing");
      xhr.onload = () => {
        cleanup();
        let body: unknown;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          reject(
            new ApiError(
              "The backend returned an invalid response.",
              xhr.status,
              "invalid_response",
            ),
          );
          return;
        }
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(messageFor(body, xhr.status));
          return;
        }
        if (
          typeof body !== "object" ||
          body === null ||
          !("document" in body) ||
          !("chunk_count" in body)
        ) {
          reject(
            new ApiError(
              "The backend returned an invalid upload response.",
              xhr.status,
              "invalid_response",
            ),
          );
          return;
        }
        resolve(body as UploadResponse);
      };
      xhr.onerror = () => {
        cleanup();
        reject(
          new ApiError(
            "Cannot reach the backend. Check the connection and CORS settings.",
          ),
        );
      };
      xhr.ontimeout = () => {
        cleanup();
        reject(
          new ApiError(
            "Upload timed out. Processing may still be running; check Neo4j before uploading again.",
          ),
        );
      };
      xhr.onabort = () => {
        cleanup();
        reject(new DOMException("Upload cancelled", "AbortError"));
      };
      if (signal?.aborted) {
        reject(new DOMException("Upload cancelled", "AbortError"));
        return;
      }
      signal?.addEventListener("abort", abort, { once: true });
      const form = new FormData();
      form.append("file", file);
      onStage("uploading");
      xhr.send(form);
    });
  },
};
export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}
