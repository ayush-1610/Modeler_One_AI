"use client";

// The evidence report (plan 2026-11-21 v2 §5 step 8): the whole Data room laid out for paper in the kick-off report's
// style. A cover with the logo, the project and the question card; then one page per section in the rail's order, its
// finding on top and the same cards and charts, still; every source written out ("file · p. 3, line 12"), since a chip
// cannot be clicked on paper; the requests with their wording; the decisions with who chose what, when and why; the
// PK-Sim inputs. A4, a page break before each section, and a footer with the rules' label, the date and "page n of m"
// (print CSS, app/styles/dataroom.css). `?print=1` opens the browser's print dialog once the charts are drawn, so the
// owner saves a PDF; no PDF is made on the server.

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Logo } from "@/components/Nav";
import { fullCard, rulesLabel } from "@/lib/dataroom";
import { useResource } from "@/lib/hooks";

import { ROOM } from "./acts";
import { SectionBody } from "./DataRoom";
import { PaperProvider, SourceProvider } from "./kit";
import { Headline } from "./overview";

const noop = () => undefined;

type Room = NonNullable<ReturnType<typeof useResource<typeof ROOM>>["data"]>;

const STAGE: Record<string, string> = {
  question: "Question card", triage: "Sorting", extract: "Reading", check: "Checking", write: "Findings",
};

/** How this report was made (the governance review, 2026-11-22): which model wrote each stage's answer for each file,
 *  where it ran (our server or the cloud service the file was sent to), the prompt's version, and each model that
 *  could not answer before it. The modeler's signature on the inputs covers this page. */
function MadeBy({ room }: { room: Room }) {
  return (
    <section className="dr-report-page" data-testid="report-made-by">
      <header className="dr-head">
        <h2 className="dr-title">How this report was made</h2>
        <p className="dr-finding">{room.made_summary || "No AI model has read this delivery yet: every value was entered by hand."}</p>
      </header>
      {room.made_by.length > 0 && (
        <div className="table-scroll">
          <table className="dr-table" data-testid="made-by-table">
            <thead><tr><th>Step</th><th>File</th><th>Model</th><th>Where it ran</th><th>Prompt</th><th>Note</th></tr></thead>
            <tbody>
              {room.made_by.map((m) => (
                <tr key={`${m.stage}|${m.file}`}>
                  <td>{STAGE[m.stage] ?? m.stage}</td>
                  <td>{m.file ? m.file.split("/").pop() : "the whole delivery"}</td>
                  <td>{m.model}</td>
                  <td>{m.service}</td>
                  <td>{m.prompt}</td>
                  <td>{[m.note, ...m.switches].filter(Boolean).join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="dr-note">
        The models only described where each table is and quoted each fact; code read every value from the files, checked
        every quote and computed the results; a modeler confirmed each decision.
      </p>
    </section>
  );
}

export function Report({ projectId, project }: { projectId: string; project: string }) {
  const room = useResource(ROOM, { project_id: projectId });
  const search = useSearchParams();
  const [today] = useState(() => new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }));
  const ready = room.data !== null;
  useEffect(() => {
    if (!ready || search.get("print") !== "1") return;
    const t = window.setTimeout(() => window.print(), 1800);   // the charts are drawn by then
    return () => window.clearTimeout(t);
  }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps
  if (room.problem) return <div className="banner err" role="alert">{room.problem}</div>;
  if (!room.data) return <p className="muted">Laying out the report…</p>;
  const r = room.data;
  const question = r.question ? fullCard(r.question) : null;
  const footer = `${rulesLabel(r.rules, true)} · ${today}`.replace(/["\\]/g, "");
  return (
    <PaperProvider value={true}>
      <SourceProvider value={noop}>
        {/* the footer of every printed page: the rules that made the room, the date, and the page count */}
        <style>{`@page { size: A4; margin: 18mm 16mm 20mm; @bottom-left { content: "${footer}"; font: 8pt sans-serif; color: #6e6e73; }
                 @bottom-right { content: "page " counter(page) " of " counter(pages); font: 8pt sans-serif; color: #6e6e73; } }`}</style>
        <article className="dr dr-report" data-testid="dataroom-report" data-no-reveal="">
          <div className="dr-report-bar">
            <button type="button" className="btn primary" onClick={() => window.print()} data-testid="report-print">Print or save as PDF</button>
          </div>
          <section className="dr-cover" data-testid="report-cover">
            <div className="dr-cover-brand"><Logo size={44} /><span>Modeler One</span></div>
            <p className="dr-cover-kind">Evidence report</p>
            <h1 className="dr-cover-title">{project}</h1>
            <p className="dr-cover-date">{today}</p>
            {question ? (
              <div className="dr-cover-question">
                <p className="dr-question">{question.question}</p>
                <dl className="dr-facts">
                  {question.regulator && <div><dt>For whom</dt><dd>{question.regulator}</dd></div>}
                  {question.approach && <div><dt>Approach</dt><dd>{question.approach}</dd></div>}
                  {question.context_of_use && <div className="wide"><dt>Context of use</dt><dd>{question.context_of_use}</dd></div>}
                  <div><dt>Question card</dt><dd>{r.question_confirmed ? "confirmed" : "a draft, not confirmed"}</dd></div>
                </dl>
                {question.products.length > 0 && (
                  <p className="dr-note">Products compared: {question.products.map((p) => `${p.name} (${p.role})`).join(" · ")}</p>
                )}
              </div>
            ) : <p className="dr-note">No question card yet.</p>}
            <Headline room={r} />
            <ol className="dr-cover-contents">
              {r.sections.map((s) => <li key={s.id}><strong>{s.title}</strong> · {s.finding}</li>)}
            </ol>
          </section>
          {r.sections.map((s) => (
            <section key={s.id} className="dr-report-page" data-testid={`report-${s.id}`}>
              <header className="dr-head">
                <h2 className="dr-title">{s.title}</h2>
                {s.finding && <p className="dr-finding">{s.finding}</p>}
              </header>
              <SectionBody id={s.id} room={r} run={null} projectId={projectId} go={noop} withRequests={false} />
            </section>
          ))}
          <MadeBy room={r} />
          <footer className="dr-report-foot">{rulesLabel(r.rules, true)} · {today}</footer>
        </article>
      </SourceProvider>
    </PaperProvider>
  );
}
