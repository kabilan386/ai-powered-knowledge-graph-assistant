import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { ChatWorkspace } from "@/components/chat/chat-workspace";
import { AnswerCard } from "@/components/chat/answer-card";
import { answer } from "./fixtures";
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: { ask: vi.fn() },
}));
describe("GraphRAG chat", () => {
  it("submits a question and renders its answer and source", async () => {
    vi.mocked(api.ask).mockResolvedValue(answer);
    const user = userEvent.setup();
    render(<ChatWorkspace />);
    expect(screen.getByText("What would you like to discover?")).toBeVisible();
    expect(screen.getByRole("button", { name: /Ask question/ })).toBeDisabled();
    await user.type(screen.getByLabelText("Your question"), answer.question);
    await user.click(screen.getByRole("button", { name: /Ask question/ }));
    await waitFor(() =>
      expect(api.ask).toHaveBeenCalledWith(
        { question: answer.question },
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByText("architecture.pdf")).toBeVisible();
    await user.click(screen.getByRole("link", { name: "[S1]" }));
    expect(
      screen.getByText("Payment Service uses Redis for caching."),
    ).toBeVisible();
    expect(screen.getByText("Page 3 · Chunk 7")).toBeVisible();
  });
  it("shows loading and an API failure without a fake answer", async () => {
    let rejectRequest: (reason: Error) => void = () => {};
    vi.mocked(api.ask).mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          rejectRequest = reject;
        }),
    );
    const user = userEvent.setup();
    render(<ChatWorkspace />);
    await user.type(screen.getByLabelText("Your question"), "Question");
    await user.click(screen.getByRole("button", { name: /Ask question/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Searching documents");
    rejectRequest(new Error("Provider unavailable"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Provider unavailable",
    );
    expect(screen.queryByText("Evidence-based answer")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Your question")).toHaveValue("Question");
  });
  it("shows insufficient evidence and no fabricated citations", () => {
    render(
      <AnswerCard
        scope="test"
        response={{
          ...answer,
          answer:
            "The available knowledge does not contain enough information to answer this question.",
          insufficient_evidence: true,
          sources: [],
          citations: [],
        }}
      />,
    );
    expect(screen.getByText("Insufficient evidence")).toBeVisible();
    expect(
      screen.queryByLabelText("Supporting sources"),
    ).not.toBeInTheDocument();
  });
  it("does not turn unknown citations into links or interpret evidence as HTML", () => {
    render(
      <AnswerCard
        scope="test"
        response={{
          ...answer,
          answer: "Unknown [S99] <script>alert(1)</script>",
        }}
      />,
    );
    expect(
      screen.queryByRole("link", { name: "[S99]" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/<script>/)).toBeVisible();
  });
  it("distinguishes graph evidence without inventing a document", async () => {
    const user = userEvent.setup();
    render(
      <AnswerCard
        scope="graph"
        response={{
          ...answer,
          answer: "Team manages Service [G1].",
          citations: ["G1"],
          sources: [
            {
              ...answer.sources[0],
              citation: "G1",
              kind: "graph",
              filename: null,
              excerpt: null,
              document_id: null,
              chunk_id: null,
              nodes: [
                { id: "team", name: "Team", type: "ORGANIZATION" },
                { id: "service", name: "Service", type: "SERVICE" },
              ],
              edges: [
                {
                  source_id: "team",
                  target_id: "service",
                  type: "MANAGES",
                  source_citations: [],
                  document_backed: false,
                },
              ],
            },
          ],
        }}
      />,
    );
    await user.click(screen.getByRole("link", { name: "[G1]" }));
    expect(screen.getByText(/No document provenance supplied/)).toBeVisible();
    expect(screen.getByText(/Graph facts preserve/)).toBeVisible();
    expect(screen.queryByText("architecture.pdf")).not.toBeInTheDocument();
  });
});
