"use client";
import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { formatBytes, maxFileSize, validateDocument } from "@/lib/documents";
import type { UploadResponse } from "@/lib/types";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Icon } from "@/components/ui/icon";
export function DocumentUploader({
  onUploaded,
}: {
  onUploaded: (response: UploadResponse) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<"idle" | "uploading" | "processing">(
    "idle",
  );
  const [success, setSuccess] = useState<UploadResponse | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  const busy = stage !== "idle";
  useEffect(() => () => controller.current?.abort(), []);
  function select(files: FileList | File[]) {
    if (busy) return;
    setSuccess(null);
    setError(null);
    if (files.length !== 1) {
      setFile(null);
      setError("Choose one document at a time.");
      return;
    }
    const selected = files[0];
    const invalid = validateDocument(selected);
    setFile(invalid ? null : selected);
    setError(invalid);
  }
  async function upload() {
    if (!file || controller.current) return;
    const invalid = validateDocument(file);
    if (invalid) {
      setError(invalid);
      return;
    }
    const request = new AbortController();
    controller.current = request;
    setError(null);
    setSuccess(null);
    setStage("uploading");
    try {
      const response = await api.upload(file, setStage, request.signal);
      if (!request.signal.aborted) {
        onUploaded(response);
        setSuccess(response);
        setFile(null);
        if (input.current) input.current.value = "";
      }
    } catch (cause) {
      if (!request.signal.aborted) setError(errorMessage(cause));
    } finally {
      if (!request.signal.aborted) setStage("idle");
      controller.current = null;
    }
  }
  return (
    <section className="panel p-6 md:p-8">
      <h2 className="text-lg font-semibold">Add a document</h2>
      <p className="mt-2 text-sm text-muted">
        Turn text into searchable evidence and connected knowledge.
      </p>
      <div
        className={`drop-zone ${dragging ? "dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (!busy) select(event.dataTransfer.files);
        }}
      >
        <div className="upload-mark">
          <Icon name="upload" width={28} height={28} />
        </div>
        <p className="mt-4 font-medium">Drop your document here</p>
        <p className="mt-2 text-sm text-muted">
          or choose a file from your device
        </p>
        <label
          className={`btn-secondary mt-5 cursor-pointer ${busy ? "opacity-50 pointer-events-none" : ""}`}
          htmlFor="document-file"
        >
          Browse files
        </label>
        <input
          id="document-file"
          ref={input}
          type="file"
          className="sr-only"
          aria-label="Choose document"
          accept=".pdf,.docx,.txt"
          disabled={busy}
          onChange={(event) => {
            if (event.target.files?.length) select(event.target.files);
            event.target.value = "";
          }}
        />
        <p className="mt-4 text-xs text-muted">
          PDF, DOCX, TXT · Up to {(maxFileSize() / 1024 / 1024).toFixed(0)} MB
        </p>
      </div>
      {file && (
        <div className="selected-file">
          <Icon name="document" />
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium text-sm">
              {file.name}
            </span>
            <span className="text-xs text-muted">{formatBytes(file.size)}</span>
          </span>
          <button
            className="text-sm text-muted underline"
            onClick={() => setFile(null)}
            disabled={busy}
          >
            Remove
          </button>
        </div>
      )}
      {error && (
        <div className="mt-4">
          <ErrorState message={error} />
        </div>
      )}
      {busy && (
        <div className="mt-5">
          <LoadingState>
            {stage === "uploading"
              ? "Uploading document…"
              : "Processing document: extracting text and building knowledge…"}
          </LoadingState>
          <p className="mt-2 text-xs text-muted">
            Keep this page open. Cancelling the request does not cancel backend
            processing.
          </p>
        </div>
      )}
      {success && (
        <div role="status" className="success-state mt-5">
          <Icon name="check" />
          <div>
            <p className="font-medium">
              {success.document.filename} uploaded · {success.chunk_count}{" "}
              chunks stored
            </p>
            <p className="mt-1 text-sm">
              Entity extraction: {success.extraction.status}. Embeddings:{" "}
              {success.embeddings.status}.
            </p>
            {(success.extraction.status === "failed" ||
              success.extraction.status === "partial" ||
              success.embeddings.status === "failed" ||
              success.embeddings.status === "partial") && (
              <p className="mt-2 text-sm">
                Some processing failed. Review the document status below before
                asking questions.
              </p>
            )}
          </div>
        </div>
      )}
      <button
        className="btn-primary mt-6 w-full justify-center"
        disabled={!file || busy}
        onClick={upload}
      >
        <Icon name="upload" />
        {busy ? "Working…" : "Upload document"}
      </button>
    </section>
  );
}
