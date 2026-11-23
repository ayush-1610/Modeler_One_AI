import { AdminTabs } from "@/components/admin/AdminParts";
import { Hero } from "@/components/kit";
import { ApiProblem, Card } from "@/components/ui";
import { getPipeline, hideUnlessAdmin, percent, when, type PipelineCounts } from "@/lib/admin";

const LEDE = "Where the intake pipeline is blind, per company and in all: the files by what became of them, where each " +
  "table's mapping came from, what no parser read, and how long each stage takes. Counts only: no file name, no value.";

// where a table's mapping came from, in the order the pipeline tries them (`mapping_shares`)
const SOURCES: [string, string][] = [["cache", "an approved layout"], ["rule", "a rule"], ["llm", "the table mapper"], ["unread", "not read"]];
const STATE_LABEL: Record<string, string> = {
  read: "read", partly_read: "partly read", unsupported: "not supported", unreadable: "not readable", failed: "failed",
  waiting: "waiting", not_read: "not read",
};
const words = (text: string) => text.replace(/_/g, " ");
const seconds = (n: number) => (n < 0.01 ? "< 0.01 s" : `${n.toFixed(2)} s`);
const listed = (counts: Record<string, number>, label: (key: string) => string = words) =>
  Object.entries(counts).map(([key, n]) => `${n} ${label(key)}`).join(", ") || "none";

/** One company's counters, or all companies' together. */
function Health({ counts, testId }: { counts: PipelineCounts; testId: string }) {
  const stages = Object.entries(counts.stage_seconds);
  return (
    <div className="pipeline-health" data-testid={testId}>
      <dl className="facts">
        <dt>Files</dt>
        <dd data-testid={`${testId}-files`}>{counts.files}: {listed(counts.files_by_state, (s) => STATE_LABEL[s] ?? words(s))}
          <span className="muted"> · {counts.projects} projects, {counts.runs} runs</span></dd>
        <dt>Where the mappings came from</dt>
        <dd>
          <ul className="pipeline-shares" data-testid={`${testId}-mapping`}>
            {SOURCES.map(([source, label]) => (
              <li key={source}><strong>{percent(counts.mapping_shares[source] ?? null)}</strong> {label}
                <span className="muted"> ({counts.mapping[source] ?? 0})</span></li>
            ))}
          </ul>
        </dd>
        <dt>Parser failures</dt><dd data-testid={`${testId}-parser-failures`}>{counts.parser_failures}</dd>
        <dt>Not supported, by extension</dt><dd data-testid={`${testId}-unsupported`}>{listed(counts.unsupported_by_extension, (ext) => ext)}</dd>
        <dt>Regions</dt><dd>{counts.regions}, {counts.regions_unread} not read · silent loss {counts.silent_loss}</dd>
        <dt>Text outside every table</dt><dd data-testid={`${testId}-outside`}>{counts.outside_items} items, {counts.outside_numeric} with a number not accounted for</dd>
        <dt>Places not found again</dt><dd data-testid={`${testId}-anchors`}>{counts.anchors_unresolved} of {counts.anchors_checked} checked</dd>
        <dt>Pages needing OCR</dt><dd data-testid={`${testId}-ocr`}>{counts.needs_ocr_pages}</dd>
        <dt>Values read</dt><dd>{counts.values}<span className="muted"> · {counts.llm_runs} runs of the table mapper</span></dd>
        {counts.damaged_logs > 0 && <><dt>Logs not readable</dt><dd>{counts.damaged_logs}</dd></>}
      </dl>
      {stages.length > 0 && (
        <div className="table-scroll mt-10">
          <table data-testid={`${testId}-stages`}>
            <caption className="sr-only">How long each stage takes</caption>
            <thead><tr><th>Stage</th><th className="num">Timings</th><th className="num">Median</th><th className="num">90th percentile</th></tr></thead>
            <tbody>
              {stages.map(([stage, s]) => (
                <tr key={stage}><td>{words(stage)}</td><td className="num">{s.n}</td><td className="num">{seconds(s.median)}</td>
                  <td className="num">{seconds(s.p90)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** The intake pipeline's health (contracts 2026-11-12 §8.10): a plain form for the date, as the page is read on the server. */
export default async function PipelinePage({ searchParams }: { searchParams: Promise<{ since?: string }> }) {
  const query = await searchParams;
  const since = query.since && /^\d{4}-\d{2}-\d{2}$/.test(query.since) ? query.since : undefined;
  const live = await getPipeline(since);
  hideUnlessAdmin(live.problem);
  const data = live.data;

  return (
    <main>
      <Hero tone="admin" eyebrow="Admin console" title="Intake pipeline" lede={LEDE} />
      <AdminTabs here="pipeline" />
      {live.problem && <ApiProblem problem={live.problem} />}
      <Card>
        <form className="admin-filter" method="get" action="/admin/pipeline" data-testid="pipeline-filter">
          <label>Since<input type="date" name="since" defaultValue={since ?? ""} /></label>
          <button type="submit" className="btn">Show</button>
        </form>
      </Card>
      {data && (
        <div data-testid="pipeline-health">
          <Card title={data.since ? `Every company, since ${data.since}` : "Every company"}>
            <Health counts={data.all} testId="pipeline-all" />
            <p className="muted mt-10">Read {when(data.generated_at)} from the pipeline&apos;s own run lines.</p>
          </Card>
          {data.companies.length === 0 && <Card><p className="muted m-0">No file has gone through the pipeline yet.</p></Card>}
          {data.companies.map((c) => (
            <Card key={c.tenant} title={c.name ? `${c.name} (${c.tenant})` : c.tenant}>
              <Health counts={c} testId={`pipeline-company-${c.tenant}`} />
            </Card>
          ))}
        </div>
      )}
    </main>
  );
}
