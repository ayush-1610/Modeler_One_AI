import { PricingSwitch } from "@/components/admin/AdminParts";
import { CompaniesTable } from "@/components/admin/CompaniesTable";
import { AddCompany } from "@/components/admin/CompanyAdmin";
import { Hero } from "@/components/kit";
import { ApiProblem } from "@/components/ui";
import { getOverview, hideUnlessAdmin, pricedAs } from "@/lib/admin";

export const metadata = { title: "Companies · Modeler One" };

/** Companies (P-24, the console redesign's slice 8): every company on the platform, its people, projects and use; a
 *  company is added here and opens on its own page. Each look is recorded on the audit trail. */
export default async function CompaniesPage({ searchParams }: { searchParams: Promise<{ priced_as?: string }> }) {
  const priced = pricedAs((await searchParams).priced_as);
  const live = await getOverview(priced);
  hideUnlessAdmin(live.problem);
  return (
    <main>
      <Hero tone="admin" eyebrow="Admin console" title="Companies" testId="admin-companies-head"
            lede="Every company on the platform: its people, its projects and what its agents used. A company opens on its own
              page, where its people are given projects and it is disabled or enabled with a reason."
            actions={<PricingSwitch priced={priced} base="/admin/companies" />} />
      {live.problem && <ApiProblem problem={live.problem} />}
      {live.data && <CompaniesTable companies={live.data.companies} priced={priced} />}
      <AddCompany />
    </main>
  );
}
