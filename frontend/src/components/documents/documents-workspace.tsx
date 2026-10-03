"use client";
import Link from "next/link";
import { useDocuments } from "./document-session";
import { DocumentUploader } from "./document-uploader";
import { DocumentList } from "./document-list";
import { PageHeader } from "@/components/ui/states";
import { Icon } from "@/components/ui/icon";
export function DocumentsWorkspace() {
  const { documents, add } = useDocuments();
  return (
    <>
      <PageHeader
        eyebrow="BUILD YOUR KNOWLEDGE"
        title="Your documents. A bigger picture."
        description="Upload your source material to build a connected, searchable knowledge base."
      />
      <div className="documents-grid">
        <div>
          <DocumentUploader onUploaded={add} />
          <DocumentList documents={documents} />
        </div>
        <aside className="workflow-panel">
          <span className="eyebrow">FROM TEXT TO KNOWLEDGE</span>
          <h2 className="mt-4 text-2xl font-semibold leading-snug">
            Give your assistant
            <br />
            something to work with.
          </h2>
          <ol className="workflow-steps">
            {[
              [
                "Extract & organize",
                "Text is extracted and divided into source chunks.",
              ],
              [
                "Connect & index",
                "Enabled AI stages identify entities, relationships, and semantic embeddings.",
              ],
              [
                "Ask & verify",
                "Search connected evidence and inspect the citations behind each answer.",
              ],
            ].map(([title, text], index) => (
              <li key={title}>
                <span className="step-number">0{index + 1}</span>
                <div>
                  <h3 className="font-medium text-sm">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">
                    {text}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          <div className="border-t border-line pt-5">
            <Link
              href="/graph"
              className="flex items-center gap-2 text-sm font-medium text-accent"
            >
              Explore the knowledge graph
              <Icon name="arrow" width={17} height={17} />
            </Link>
            <Link
              href="/chat"
              className="mt-4 flex items-center gap-2 text-sm font-medium text-accent"
            >
              Ask your first question
              <Icon name="arrow" width={17} height={17} />
            </Link>
          </div>
        </aside>
      </div>
    </>
  );
}
