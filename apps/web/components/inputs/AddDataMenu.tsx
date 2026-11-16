"use client";

// The head's "Add data" (plan 2026-11-14 slice 1): one menu for every way data comes into Inputs, in the design's order.
// The client's files are added for the area their data belong to (each takes the tag its name says, else the area's),
// and the client-data template is downloaded here; observed data is digitized from a figure, typed in, or searched for by
// the observed-data agent (offered only while AI is on), each opening its tool on Clinical studies; the page's other
// sources (the structured sources and the literature, a published OSP model) are passed in by the workspace. The file
// inputs sit outside the menu's panel, so they stay in the page while it is closed.
//
// A link on the page opens it on the files of one area, for a product (`open`: final review round 5, "add a product's
// dissolution data" for a product with no card of its own): the action is focused and says whose data it adds. A file
// says its product itself (the dissolution register reads it from the file), so no product is chosen here.

import { useEffect, useRef, useState, type ReactNode } from "react";

import { Menu } from "@/components/kit/Menu";
import type { DataTab } from "@/lib/fileTags";

import type { Run } from "./InputsTodo";
import { ACCEPT, AREA_FILES, FILE_AREAS, addClientFiles } from "./TabFiles";

const UPLOAD_LABEL: Record<DataTab, string> = {
  studies: "Clinical and bioanalytical files…", formulations: "Formulation and dissolution files…",
  compound: "In vitro and physico-chemistry files…",
};
/** Open "Add data" on the files of an area (`at`: each ask opens it again), for a product when one is named. */
export type AddDataOpen = { at: number; area: DataTab; product?: string };

export function AddDataMenu({ projectId, run, onTemplate, onDigitize, onTypeTable, onFindObserved, open, children }: {
  projectId: string; run: Run;
  onTemplate: () => void; onDigitize: () => void; onTypeTable: () => void;
  /** the observed-data agent; absent while AI is off */
  onFindObserved?: () => void;
  open?: AddDataOpen | null;
  children?: ReactNode;
}) {
  const inputs = useRef<Partial<Record<DataTab, HTMLInputElement | null>>>({});
  // the product a link opened the menu for, said on its action while the menu is open
  const [forProduct, setForProduct] = useState<{ area: DataTab; product: string } | null>(null);
  useEffect(() => { if (open?.product) setForProduct({ area: open.area, product: open.product }); }, [open?.at]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <Menu label="Add data" testId="inputs-add-data" open={open ? { at: open.at, focus: `add-files-${open.area}` } : null}
            onToggle={(opened) => { if (!opened) setForProduct(null); }}>
        <p className="menu-heading">The client&apos;s files</p>
        {FILE_AREAS.map((area) => (
          <button key={area} type="button" className="menu-item" data-testid={`add-files-${area}`}
                  title={`Add the client's ${AREA_FILES[area]}; a file whose name says otherwise is filed where its name says`}
                  onClick={() => inputs.current[area]?.click()}>
            {UPLOAD_LABEL[area]}
            {forProduct?.area === area && <span className="muted" data-testid={`add-files-${area}-for`}> · the dissolution data of {forProduct.product}</span>}
          </button>
        ))}
        <button type="button" className="menu-item" data-testid="add-template" onClick={onTemplate}
                title="A workbook the client fills in; it is read cell by cell, with no AI">
          Download the client-data template
        </button>
        <p className="menu-heading">Observed data</p>
        <button type="button" className="menu-item" data-testid="add-digitize" onClick={onDigitize}
                title="Read a published figure's points against calibrated axes, on Clinical studies">Digitize a figure</button>
        <button type="button" className="menu-item" data-testid="add-typed-table" onClick={onTypeTable}
                title="A study's facts and its mean profile typed in by hand, on Clinical studies">Type a table in</button>
        {onFindObserved && (
          <button type="button" className="menu-item" data-testid="add-find-observed" onClick={onFindObserved}
                  title="The observed-data agent searches the literature; datasets appear on Clinical studies as it records them">
            Find observed data <span className="muted">· AI</span>
          </button>
        )}
        {children && <><p className="menu-heading">Values from elsewhere</p>{children}</>}
      </Menu>
      {FILE_AREAS.map((area) => (
        <input key={area} ref={(el) => { inputs.current[area] = el; }} type="file" multiple hidden accept={ACCEPT}
               data-testid={`client-upload-${area}`} aria-label={`Add the client's ${AREA_FILES[area]}`}
               onChange={(e) => { void addClientFiles(projectId, run, e.target.files, area); e.target.value = ""; }} />
      ))}
    </>
  );
}
