// File tags at upload (docs/plans/2026-11-03-inputs-and-client-data.md §3.1; the owner, 2026-11-03): on the "Start from
// proposal" page and in "+ Add data", each file says what it is at a high level. The tag is a hint for reading the file,
// not a fact: code pre-fills it from the name (the rules mirror `modeler_intake.file_tags`; change both together), and
// once the file is read, proposes another tag when the content says otherwise. The person keeps one; no reason is asked.

import type { Schema } from "@/lib/api";

export type TagKind = Schema<"FileTagView">["kind"];
/** Where a file goes: the proposal (read for the brief) or a client file with its tag. */
export type FileTag = "proposal" | TagKind;

export const TAG_LABELS: Record<TagKind, string> = {
  formulation: "Formulation or dissolution",
  clinical: "Clinical study",
  bioanalytical: "Bioanalytical",
  in_vitro: "In vitro or physico-chemistry",
  other: "Other client data",
};
export const TAG_KINDS = Object.keys(TAG_LABELS) as TagKind[];

const NAME_RULES: [FileTag, RegExp][] = [
  ["proposal", /proposal|quotation|\bsow\b|statement of work/],
  ["bioanalytical", /bioanaly|\blc ?ms|\bbmv\b|method valid|assay valid/],
  ["in_vitro", /\badme\b|in ?vitro|\bcaco|\bppb\b|protein binding|microsom|hepatocyte|physchem|physico|solubil|permeab|\blog ?[pd]\b|\bpka\b/],
  ["formulation", /dissol|formulat|composition|\bbatch|\blots?\b|\bcoa\b|tablet|capsule/],
  ["clinical", /\bpk\b|pharmacokin|\bconc|\bcsr\b|protocol|clinical|\bstudy\b|subject|demograph|dosing|plasma|\bnca\b/],
];
const TABLE = /\.(xlsx|xlsm|xls|csv|tsv)$/i;

/** What a file's name says it is; a table nothing names is "other" client data, a document the proposal or an annex. */
export function guessTag(name: string): FileTag {
  const text = name.toLowerCase().replace(/[_\-.]+/g, " ");
  const hit = NAME_RULES.find(([, rule]) => rule.test(text));
  return hit ? hit[0] : TABLE.test(name) ? "other" : "proposal";
}

/** A study code in a clinical file's name ("EXZ-101_PK.xlsx" → "EXZ-101"), to pre-fill which study it is. */
export function guessStudy(name: string): string {
  const match = /\b([A-Z]{2,6}-?\d{2,6}(?:-\d{2,6})?)\b/.exec(name.replace(/_/g, " "));
  return match ? match[1] : "";
}

/** The `tags` form field of an upload: `{"<file name>": {"kind": …, "study": …}}` for the client files. */
export function tagsField(files: { file: File; tag: FileTag; study: string }[]): string {
  const tags: Record<string, { kind: TagKind; study: string }> = {};
  files.forEach(({ file, tag, study }) => {
    if (tag !== "proposal") tags[file.name] = { kind: tag, study: tag === "clinical" ? study.trim() : "" };
  });
  return JSON.stringify(tags);
}

export function tagLabel(kind: TagKind | null | undefined): string {
  return kind ? TAG_LABELS[kind] : "not tagged";
}
