import Link from "next/link";

import { Hero } from "@/components/kit";
import { ApiProblem } from "@/components/ui";
import { serverGet } from "@/lib/api";
import { getCompoundCpf, getProject } from "@/lib/reads";

// A project's compounds (P-17, the console redesign's slice 3; before, a card on the Run page): each one's role in the
// model system and how complete its parameter framework (CPF) is. The values themselves are filled in on Inputs (one home
// per decision); each compound opens its CPF, the system of record every simulation is regenerated from.
export default async function ProjectCompounds({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const [live, liveSystem] = await Promise.all([
    getProject(projectId), serverGet("/api/v1/projects/{project_id}/system", { project_id: projectId }),
  ]);
  const project = live.data;
  const roles = new Map((liveSystem.data?.system?.compounds ?? []).map((c) => [c.compound, c.role]));
  const cpfs = project ? await Promise.all(project.compounds.map((c) => getCompoundCpf(projectId, c))) : [];
  const base = `/projects/${encodeURIComponent(projectId)}`;
  return (
    <main>
      <Hero title="Compounds" lede="Each compound's role in the model and how complete its parameter framework is. Values are filled in on Inputs." />
      {live.problem && <ApiProblem problem={live.problem} />}
      {project && (
        <section className="tbl" aria-label="Compounds" data-testid="compounds-table">
          {project.compounds.length === 0 ? <div className="tbl-empty">No compound yet: it is named on Start.</div> : (
            <div className="tbl-scroll">
              <table>
                <thead><tr><th scope="col">Compound</th><th scope="col">Role</th><th scope="col" className="num">Complete</th><th scope="col">Values</th></tr></thead>
                <tbody>
                  {project.compounds.map((c, i) => {
                    const cpf = cpfs[i]?.data ?? null;
                    return (
                      <tr key={c} data-testid={`compound-row-${c}`}>
                        <td><Link href={`${base}/compounds/${encodeURIComponent(c)}`} data-testid={`overview-compound-${c}`}>{c}</Link></td>
                        <td>{roles.get(c) ?? (project.compounds.length === 1 ? "the compound modelled" : "—")}</td>
                        <td className="num">{cpf ? `${Math.round(cpf.completeness * 100)} %` : <span className="muted">no values yet</span>}</td>
                        <td><Link href={`${base}/inputs?tab=compound`}>Fill in on Inputs</Link></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
