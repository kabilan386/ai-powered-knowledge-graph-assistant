import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import { validateDocument } from "@/lib/documents";
import { DocumentUploader } from "@/components/documents/document-uploader";
import { DocumentList } from "@/components/documents/document-list";
import { upload } from "./fixtures";
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  api: { upload: vi.fn() },
}));
describe("Document upload", () => {
  it.each(["file.pdf", "file.DOCX", "file.txt"])(
    "accepts supported %s",
    (name) => {
      expect(validateDocument(new File(["text"], name))).toBeNull();
    },
  );
  it("rejects unsupported, empty, and oversized documents", () => {
    expect(validateDocument(new File(["text"], "file.exe"))).toMatch(/PDF/);
    expect(validateDocument(new File([], "file.txt"))).toMatch(/empty/);
    expect(validateDocument(new File(["too long"], "file.txt"), 2)).toMatch(
      /limit/,
    );
  });
  it("uploads and displays actual processing status", async () => {
    vi.mocked(api.upload).mockImplementation(async (_file, onStage) => {
      onStage("processing");
      return upload;
    });
    const onUploaded = vi.fn();
    const user = userEvent.setup();
    render(<DocumentUploader onUploaded={onUploaded} />);
    await user.upload(
      screen.getByLabelText("Choose document"),
      new File(["content"], "architecture.pdf"),
    );
    await user.click(screen.getByRole("button", { name: "Upload document" }));
    expect(await screen.findByText(/12 chunks stored/)).toBeVisible();
    expect(
      screen.getByText("Entity extraction: completed. Embeddings: completed."),
    ).toBeVisible();
    expect(onUploaded).toHaveBeenCalledWith(upload);
  });
  it("shows backend failure and retains the selected file", async () => {
    vi.mocked(api.upload).mockRejectedValue(new Error("Upload rejected"));
    const user = userEvent.setup();
    const onUploaded = vi.fn();
    render(<DocumentUploader onUploaded={onUploaded} />);
    await user.upload(
      screen.getByLabelText("Choose document"),
      new File(["content"], "file.txt"),
    );
    await user.click(screen.getByRole("button", { name: "Upload document" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Upload rejected",
    );
    expect(screen.getByText("file.txt")).toBeVisible();
    expect(onUploaded).not.toHaveBeenCalled();
  });
  it("validates dropped files and handles empty files", () => {
    render(<DocumentUploader onUploaded={vi.fn()} />);
    const drop = screen.getByText("Drop your document here").parentElement!;
    fireEvent.drop(drop, {
      dataTransfer: { files: [new File(["bad"], "file.exe")] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("PDF, DOCX, or TXT");
    fireEvent.drop(drop, {
      dataTransfer: { files: [new File([], "file.txt")] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("empty");
  });
  it("shows pending processing without percentages", async () => {
    vi.mocked(api.upload).mockImplementation((_file, onStage) => {
      onStage("processing");
      return new Promise(() => {});
    });
    const user = userEvent.setup();
    render(<DocumentUploader onUploaded={vi.fn()} />);
    await user.upload(
      screen.getByLabelText("Choose document"),
      new File(["text"], "file.txt"),
    );
    await user.click(screen.getByRole("button", { name: "Upload document" }));
    expect(screen.getByRole("status")).toHaveTextContent("Processing document");
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    expect(screen.queryByText(/100%/)).not.toBeInTheDocument();
  });
  it("renders empty and partial session history honestly", () => {
    const { rerender } = render(<DocumentList documents={[]} />);
    expect(
      screen.getByText("No documents uploaded in this session"),
    ).toBeVisible();
    rerender(
      <DocumentList
        documents={[
          {
            ...upload,
            extraction: { ...upload.extraction, status: "partial" },
            embeddings: { ...upload.embeddings, status: "disabled" },
          },
        ]}
      />,
    );
    expect(screen.getByText("partial")).toBeVisible();
    expect(screen.getByText("disabled")).toBeVisible();
    expect(screen.getByText("Text stored")).toBeVisible();
  });
});
