"use client";

// The Data room (plan 2026-11-21 v2 §5, §10): the delivery's way in on top, then a rail of sections, each with its status
// dot, and the section shown beside it: its one-line finding first, at most three cards, every value with its source
// chip, its data requests at the bottom. The section is kept in the address (`?section=`), so a link opens it. Only the
// PK-Sim inputs section speaks PK-Sim's own names.

import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { SECTION_AREA, SECTION_STATE, rulesLabel, type Chip, type Room, type Run, type Section } from "@/lib/dataroom";
import { readAgain, useResource } from "@/lib/hooks";

import { ActsContext, PUBLICATION, ROOM, RUN, UPLOADS, useActs } from "./acts";
import { Intake } from "./Intake";
import { Dot, Nothing, SourceProvider } from "./kit";
import { Files, Overview } from "./overview";
import { Clinical, Dissolution, Formulation, Observed, Solubility, Values } from "./science";
import { SourceDrawer } from "./SourceDrawer";
import { Decisions, Inputs, Plan, Requests } from "./work";

export const OVERVIEW: Section = { id: "overview", title: "Overview", finding: "", status: "ok", computed: "" };

/** One section's cards (the page and the report draw the same). */
export function SectionBody({ id, room, run, projectId, go, withRequests = true }: {
  id: string; room: Room; run: Run | null; projectId: string; go: (section: string) => void;
  /** The section's own data requests at its end (the report lists them once, in Data requests). */
  withRequests?: boolean;
}): ReactNode {
  const extractSkipped = run?.stages.find((s) => s.id === "extract")?.state === "skipped";
  const why = extractSkipped ? " The extraction step has no AI model set up yet: the admin console sets one." : "";
  const area = SECTION_AREA[id];
  const body = (() => {
    switch (id) {
      case "overview": return <Overview room={room} go={go} />;
      case "files": return <Files room={room} run={run} />;
      case "substance": return <Values values={room.substance} title="Drug substance" empty={`No drug-substance property was found yet.${why}`} />;
      case "adme": return <Values values={room.adme} title="Absorption, distribution, metabolism, elimination" empty={`No ADME fact was found yet.${why}`} />;
      case "formulation": return <Formulation room={room} />;
      case "solubility": return <Solubility room={room} />;
      case "dissolution": return <Dissolution room={room} />;
      case "clinical": return <Clinical room={room} />;
      case "observed": return <Observed room={room} />;
      case "decisions": return <Decisions room={room} />;
      case "requests": return <Requests room={room} />;
      case "plan": return <Plan room={room} />;
      case "inputs": return <Inputs room={room} projectId={projectId} />;
      default: return <Nothing>No such section.</Nothing>;
    }
  })();
  return <>{body}{area && withRequests && <Requests room={room} area={area} />}</>;
}

function Rail({ sections, current, go }: { sections: Section[]; current: string; go: (id: string) => void }) {
  return (
    <>
      <nav className="dr-rail" aria-label="Data room sections" data-testid="dataroom-rail">
        <ul>
          {sections.map((s) => (
            <li key={s.id}>
              <button type="button" className={current === s.id ? "on" : ""} aria-current={current === s.id ? "page" : undefined}
                      onClick={() => go(s.id)} data-testid={`rail-${s.id}`} title={s.id === "overview" ? undefined : `${s.title}: ${SECTION_STATE[s.status]}`}>
                {s.id === "overview" ? <span className="dr-dot-wrap"><span className="dr-dot home" aria-hidden /></span> : <Dot status={s.status} />}
                <span>{s.title}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <label className="dr-rail-select">
        <span className="sr-only">Section</span>
        <select value={current} onChange={(e) => go(e.target.value)} data-testid="dataroom-section-select">
          {sections.map((s) => <option key={s.id} value={s.id}>{s.title}{s.id === "overview" ? "" : ` · ${SECTION_STATE[s.status]}`}</option>)}
        </select>
      </label>
    </>
  );
}

export function DataRoom({ projectId }: { projectId: string }) {
  const params = { project_id: projectId };
  const client = useQueryClient();
  const router = useRouter();
  const here = usePathname();
  const search = useSearchParams();
  const room = useResource(ROOM, params);
  const run = useResource(RUN, params, { poll: (d) => d.state === "running", interval: 1500 });
  const uploads = useResource(UPLOADS, params);
  const acts = useActs(projectId);
  const [chip, setChip] = useState<Chip | null>(null);
  const top = useRef<HTMLHeadingElement>(null);

  // the run's end changes the room: read it again once, when the run stops
  const was = useRef<string | null>(null);
  useEffect(() => {
    const state = run.data?.state ?? null;
    if (was.current === "running" && state !== "running") void readAgain(client, [ROOM, PUBLICATION, UPLOADS]);
    was.current = state;
  }, [run.data?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  const sections = [OVERVIEW, ...(room.data?.sections ?? [])];
  const asked = search.get("section") ?? "overview";
  const current = sections.some((s) => s.id === asked) ? asked : "overview";
  const go = (id: string) => {
    const q = new URLSearchParams(search.toString());
    if (id === "overview") q.delete("section"); else q.set("section", id);
    router.replace(`${here}${q.size ? `?${q}` : ""}`, { scroll: false });
    window.setTimeout(() => top.current?.focus({ preventScroll: false }), 0);
  };
  const section = sections.find((s) => s.id === current)!;
  const finding = current === "overview"
    ? (room.data?.question?.question ? "Where the delivery stands, and what needs you first." : "Start with the question the modelling must answer.")
    : section.finding;

  return (
    <ActsContext.Provider value={acts}>
      <SourceProvider value={setChip}>
        {/* every section shown at once, never faded in as it scrolls into view (a working page, as Inputs) */}
        <div className="dr" data-testid="dataroom" data-no-reveal="">
          <Intake projectId={projectId} run={run.data} files={room.data?.files.length ?? 0} uploads={uploads.data?.uploads.length ?? 0} />
          {room.problem && <div className="banner err" role="alert">{room.problem}</div>}
          {room.data && (
            <div className="dr-layout">
              <Rail sections={sections} current={current} go={go} />
              <div className="dr-main" data-testid={`section-${current}`}>
                <header className="dr-head">
                  <h2 ref={top} tabIndex={-1} className="dr-title">{section.title}</h2>
                  {finding && <p className="dr-finding" data-testid="section-finding">{finding}</p>}
                </header>
                <SectionBody id={current} room={room.data} run={run.data} projectId={projectId} go={go} />
              </div>
            </div>
          )}
          {!room.data && !room.problem && <p className="muted">Opening the Data room…</p>}
          <p className="dr-foot muted">
            {room.data?.rules && <span>{rulesLabel(room.data.rules)}</span>}
          </p>
        </div>
        {chip && <SourceDrawer projectId={projectId} chip={chip} onClose={() => setChip(null)} />}
      </SourceProvider>
    </ActsContext.Provider>
  );
}
