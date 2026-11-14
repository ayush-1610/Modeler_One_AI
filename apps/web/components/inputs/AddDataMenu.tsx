"use client";

// The head's "Add data" (plan 2026-11-14 slice 1): one menu for every way data comes into Inputs. The client's files are
// added for the area their data belong to (each takes the tag its name says, else the area's); the page's other sources
// (the structured sources and the literature, a published OSP model) are passed in by the workspace. The file inputs
// sit outside the menu's panel, so they stay in the page while it is closed.

import { useRef, type ReactNode } from "react";

import { Menu } from "@/components/kit/Menu";
import type { DataTab } from "@/lib/fileTags";

import type { Run } from "./InputsTodo";
import { ACCEPT, AREA_FILES, FILE_AREAS, addClientFiles } from "./TabFiles";

const UPLOAD_LABEL: Record<DataTab, string> = {
  studies: "Clinical and bioanalytical files…", formulations: "Formulation and dissolution files…",
  compound: "In vitro and physico-chemistry files…",
};

export function AddDataMenu({ projectId, run, children }: { projectId: string; run: Run; children?: ReactNode }) {
  const inputs = useRef<Partial<Record<DataTab, HTMLInputElement | null>>>({});
  return (
    <>
      <Menu label="Add data" testId="inputs-add-data">
        <p className="menu-heading">The client&apos;s files</p>
        {FILE_AREAS.map((area) => (
          <button key={area} type="button" className="menu-item" data-testid={`add-files-${area}`}
                  title={`Add the client's ${AREA_FILES[area]}; a file whose name says otherwise is filed where its name says`}
                  onClick={() => inputs.current[area]?.click()}>
            {UPLOAD_LABEL[area]}
          </button>
        ))}
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
