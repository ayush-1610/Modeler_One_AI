"use client";

// Every company on the platform as a console table (P-24, the console redesign's slice 8): its people, its projects
// (active and archived), what its agents used and what that would cost. Sortable and filterable; each company opens
// on its own page, where it is disabled or enabled with a reason.

import Link from "next/link";

import { Table } from "@/components/kit/Table";
import type { Schema } from "@/lib/api";
import { tokens, usd, type PricedAs } from "@/lib/admin";

type Company = Schema<"CompanyRow">;

export function CompaniesTable({ companies, priced }: { companies: Company[]; priced: PricedAs }) {
  return (
    <Table title="Companies" rows={companies} rowKey={(c) => c.tenant_id} rowTestId={(c) => `company-row-${c.tenant_id}`}
           testId="admin-companies"
           filter={{ placeholder: "Filter companies", testId: "companies-filter", text: (c) => `${c.tenant_id} ${c.name}` }}
           columns={[
             { key: "company", label: "Company", sort: (c) => c.tenant_id,
               render: (c) => (
                 <>
                   <Link href={`/admin/companies/${encodeURIComponent(c.tenant_id)}?priced_as=${priced}`} prefetch={false}>{c.tenant_id}</Link>
                   {c.name && <div className="muted fs-12">{c.name}</div>}
                   {c.disabled && <span className="chip high" data-testid={`company-disabled-${c.tenant_id}`}>disabled</span>}
                 </>
               ) },
             { key: "people", label: "People", num: true, sort: (c) => c.people, render: (c) => c.people },
             { key: "projects", label: "Projects", num: true, sort: (c) => c.projects, render: (c) => c.projects },
             { key: "archived", label: "Archived", num: true, sort: (c) => c.archived, render: (c) => c.archived || "—" },
             { key: "runs", label: "Runs", num: true, sort: (c) => c.usage.runs, render: (c) => c.usage.runs },
             { key: "failed", label: "Did not finish", num: true, sort: (c) => c.usage.failed_runs, render: (c) => c.usage.failed_runs || "—" },
             { key: "tokens", label: "Tokens in / out", num: true, sort: (c) => c.usage.input_tokens + c.usage.output_tokens,
               render: (c) => `${tokens(c.usage.input_tokens)} / ${tokens(c.usage.output_tokens)}` },
             { key: "cost", label: "Est. cost", num: true, sort: (c) => c.usage.usd, render: (c) => usd(c.usage.usd) },
           ]}
           empty="No company yet. Add the first one below." />
  );
}
