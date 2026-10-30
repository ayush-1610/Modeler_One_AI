# The project document library (plan)

Status: **agreed** (the owner, 2026-10-29: decisions 10–13). **PR 1, the library page, is built** (2026-10-29).
**PR 2, "Add data" and withdrawal, is built** (2026-10-30). **PR 3, the agents library first, is built**
(2026-10-30). This plan comes from the owner's marks on the Start page review (page review 1, 2026-10-27): rows
`b1.files` and `b1.add` (move), and `f.viewer` (move).

## What the owner asked for
- **"Add data" in the left sidebar,** directly above a "Project Document Library" entry.
  - It opens a centred card over the current screen, with the page dimmed underneath.
  - Files can be added at any stage of a project: PDF, Word, Excel, JSON, Markdown, CSV.
  - On upload, the person says which page, workflow or task the file relates to.
- **One library per project,** isolated from every other project: its files, edits and additions stay with it.
- **A table** with:
  - the document name and an access link;
  - the source (user or agent);
  - category and subcategory, and a short description;
  - status and format;
  - **"Data extracted / project contribution":** the values, parameters and units taken from the document, each traceable
    to it, or how else it was used (parameterisation, validation, a decision). If nothing was extracted, it says so.
- **Search, filtering, sorting, version history** and traceability of where each file was used. The structure stays
  flexible, so fields and categories can change later.
- **Agents use the library first:**
  - Every agent of the project reads it, and checks it before searching outside.
  - What an agent retrieves from the internet (after checking its relevance) is saved back into the same library, with
    its provenance.
- **Sources at the value:** the document viewer leaves Start's side panel. Each value shows its source where it is
  used, and that is the only place a source is named.

## What exists today (on `main`)
- **`modeler_project.documents.DocumentLibrary`** is already one library per project.
  - Each file is a DOCUMENT artifact in the project's workspace: write-once blob under its SHA-256, versioned, and in
    the audit chain.
  - It holds the extracted page texts.
  - It offers `search`, which the intake agent (A1) and the literature agent (A2) already use.
- **Roles:** proposal, annex, context, client file, paper, retrieved record, other.
- **Retrieved database answers** (PubChem) are stored as documents too, so a value from a database is quoted from
  exactly what the database returned.
- **The links between documents and values exist already:**
  - every evidence item cites `(doc_sha256, page, quote)`;
  - every brief value cites its quote;
  - a dataset names its document.

  So the "data extracted" column can be computed from the register, not typed.
- **Isolation:** every store path is `<tenant>/<project>/…`, and the API checks project membership on each route.

## Proposed build (three PRs, each to `main`)
1. **The library page** `/projects/[id]/library` (read only), and its table.
   - **Columns:** name and link, source (who added it: a person, or which agent), role / category, format, pages,
     added (when and by whom), and "data extracted / contribution".
   - **The contribution column** lists the evidence items, brief fields and datasets that cite the document, each with
     its value and unit, and links to where it is used.
   - Search, filters and sorting over the table. A document's versions come from its artifact history.
   - The sidebar gets "Project Document Library" for the open project.
   - Start's file list moves here.
2. **"Add data"**: the sidebar entry and the centred card.
   - Upload, with "what it relates to": a step and, optionally, a task.
   - It stores that in the library's record, `<root>/<tenant>/projects/<pid>/library.json`, with the withdrawals, each
     change an audit event. Built differently from the first idea, a new field of `DocumentRecord`: a document's
     next version would mark the brief and the client data, which derive from the documents, stale.
   - The type is guessed from the file: a workbook goes to client data, the rest to documents; the guess can be
     switched.
   - Start's "Add files" is then removed.
3. **Agents library first.**
   - The literature agent (A2) searches the library before searching outside.
   - What it fetches is stored with role `paper` and its provenance (URL, DOI, when, by which agent) before a value is
     taken from it.
   - The document's status says whether its full text is held or only its abstract.
   - Built (2026-10-30): `search_literature` lists the library's matches first and marks the papers it holds; a paper
     already stored is read from the library, not fetched again; the provenance is the library record's `Retrieval`.
     The agents still search Europe PMC when the library has nothing: "library first" orders the search, it does not
     forbid the outside one.
   - Licensing is respected: a paper the project has no right to store is kept as a reference with its abstract, and
     access is requested (the existing `access_requests`).

## The owner's answers (2026-10-29)
1. **Categories:** the roles above plus "what it relates to" (a step, and optionally a task).
2. **Removing a document:** it is withdrawn with a reason, hidden from the agents and marked in the table, never erased.
3. **Agent retrieval:** agents store open-access papers only. A paywalled paper stays a reference with its abstract,
   unless the owner uploads it.
