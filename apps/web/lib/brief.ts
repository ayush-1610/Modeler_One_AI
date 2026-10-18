// The documents a project's brief and evidence are read from (`GET /projects/{id}/documents`, the API's response model).
// The brief itself is read and edited on Start, through lib/start.ts.

import type { Schema } from "./api";

export type DocumentView = Schema<"DocumentView">;
