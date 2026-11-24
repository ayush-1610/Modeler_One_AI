"use client";

// "Add documents" on the Documents page (P-18, the console redesign's slice 7): the same "Add data" card the side
// navigation opens, from the page that lists what it adds.

import { useState } from "react";
import { createPortal } from "react-dom";

import { AddData } from "@/components/library/AddData";

export function AddDocuments({ projectId }: { projectId: string }) {
  const [adding, setAdding] = useState(false);
  return (
    <>
      <button type="button" className="btn primary" data-testid="library-add" onClick={() => setAdding(true)}>Add documents</button>
      {adding && createPortal(<AddData projectId={projectId} step="" onClose={() => setAdding(false)} />, document.body)}
    </>
  );
}
