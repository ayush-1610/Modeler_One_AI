"use client";

// "Read this sheet" from a card (final review OWN-2 c): a sheet-form draft whose own words name cells that are neither a
// value nor marked ("Cells say '12.3*', '>1000': mark them as 'no sample' or correct the file") opens its sheet in Client
// files, in the sheet reader, with those cells' texts added to the cells that mean no sample. The person checks the
// sheet and saves it; nothing is read or kept until then. The Inputs page provides the opener; elsewhere none is given
// and the draft says where to go instead.

import { createContext, useContext } from "react";

/** A sheet to open in the sheet reader: the client file, the sheet, and the cell texts to add as "no sample". */
export type SheetAsk = { file: string; sheet: string; noSample: string[]; at: number };

export const OpenSheetContext = createContext<((ask: Omit<SheetAsk, "at">) => void) | null>(null);

/** The page's opener of a client file's sheet in the sheet reader, when the page has one. */
export const useOpenSheet = () => useContext(OpenSheetContext);
