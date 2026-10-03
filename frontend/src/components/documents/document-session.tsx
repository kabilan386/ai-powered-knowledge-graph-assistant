"use client";
import { createContext, useContext, useState, type ReactNode } from "react";
import type { UploadResponse } from "@/lib/types";
const Context = createContext<{
  documents: UploadResponse[];
  add: (document: UploadResponse) => void;
} | null>(null);
export function DocumentSession({ children }: { children: ReactNode }) {
  const [documents, setDocuments] = useState<UploadResponse[]>([]);
  return (
    <Context.Provider
      value={{
        documents,
        add: (document) =>
          setDocuments((current) => [
            document,
            ...current.filter(
              (item) => item.document.id !== document.document.id,
            ),
          ]),
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useDocuments() {
  const value = useContext(Context);
  if (!value) throw new Error("DocumentSession is required");
  return value;
}
