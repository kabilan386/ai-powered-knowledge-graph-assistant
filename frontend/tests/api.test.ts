import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, apiBaseUrl, ApiError } from "@/lib/api";
import { answer, graph, upload } from "./fixtures";
beforeEach(() =>
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://backend.test/"),
);
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
describe("API client", () => {
  it("sends the question to the configured backend", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(answer));
    vi.stubGlobal("fetch", fetcher);
    expect(await api.ask({ question: answer.question })).toEqual(answer);
    expect(fetcher).toHaveBeenCalledWith(
      "http://backend.test/api/graphrag/ask",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ question: answer.question }),
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
      }),
    );
  });
  it("loads the graph and preserves error messages", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json(graph))
      .mockResolvedValueOnce(
        Response.json(
          {
            error: {
              code: "graph_unavailable",
              message: "Temporarily unavailable",
            },
          },
          { status: 503 },
        ),
      );
    vi.stubGlobal("fetch", fetcher);
    expect(await api.graph()).toEqual(graph);
    await expect(api.graph()).rejects.toMatchObject({
      message: "Temporarily unavailable",
      status: 503,
      code: "graph_unavailable",
    });
  });
  it("handles validation, network, and non-JSON responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(Response.json({ detail: [] }, { status: 422 }))
        .mockRejectedValueOnce(new TypeError("private"))
        .mockResolvedValueOnce(new Response("invalid")),
    );
    await expect(api.graph()).rejects.toThrow("Check your input");
    await expect(api.graph()).rejects.toThrow("Cannot reach");
    await expect(api.graph()).rejects.toMatchObject({
      code: "invalid_response",
    });
  });
  it("requires a safe configured URL", () => {
    for (const value of [
      "",
      "invalid",
      "file:///tmp",
      "http://user:secret@host",
      "http://host?x=1",
    ]) {
      vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", value);
      expect(apiBaseUrl).toThrow(ApiError);
    }
  });
  it("preserves caller cancellation", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("Cancelled", "AbortError")),
    );
    const controller = new AbortController();
    controller.abort();
    await expect(api.graph(controller.signal)).rejects.toMatchObject({
      name: "AbortError",
    });
  });
  it("uploads multipart data and reports actual transfer completion", async () => {
    const holder: { instance?: FakeXHR } = {};
    class FakeXHR {
      upload = { onload: () => {} };
      onload = () => {};
      onerror = () => {};
      ontimeout = () => {};
      onabort = () => {};
      status = 201;
      responseText = JSON.stringify(upload);
      timeout = 0;
      open = vi.fn();
      abort = vi.fn();
      send = vi.fn((form: FormData) => {
        expect(form.get("file")).toBeInstanceOf(File);
        this.upload.onload();
        this.onload();
      });
      constructor() {
        holder.instance = this;
      }
    }
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const stage = vi.fn();
    expect(await api.upload(new File(["content"], "file.txt"), stage)).toEqual(
      upload,
    );
    expect(holder.instance!.open).toHaveBeenCalledWith(
      "POST",
      "http://backend.test/api/documents/upload",
    );
    expect(stage.mock.calls).toEqual([["uploading"], ["processing"]]);
  });
  it("reports upload transport failure without returning document metadata", async () => {
    class FailedXHR {
      upload = { onload: () => {} };
      onload = () => {};
      onerror = () => {};
      ontimeout = () => {};
      onabort = () => {};
      open = vi.fn();
      abort = vi.fn();
      send = () => this.ontimeout();
    }
    vi.stubGlobal("XMLHttpRequest", FailedXHR);
    await expect(
      api.upload(new File(["content"], "file.txt"), vi.fn()),
    ).rejects.toThrow(/timed out/i);
  });
});
