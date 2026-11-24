# For the PBPK SME: two findings about the acceptance ruleset (2026-11-24)

**From:** Modeler One (owner decision D7 of `docs/plans/2026-11-24-data-story-next-phase.md`).
**File:** `packages/pbpk-domain/src/pbpk_domain/rulesets/pbpk_acceptance_criteria.yaml`, version `2026.2-draft`,
status `UNVERIFIED`. The file is locked and **has not been edited**.
**Found by:** the literature review `docs/research/2026-11-24-regulatory-data-by-context-of-use.md` (§4 and §9).

## Finding 1: the title cited for `guest_2011` is not the paper's

| | Text |
|---|---|
| **The ruleset says** (line 27) | "Guest EJ et al. Assessment of algorithms for predicting drug-drug interactions via inhibition mechanisms. Drug Metab Dispos 2011;39:170-173" |
| **PubMed has** (PMID 21036951, doi:10.1124/dmd.110.036103) | Guest EJ et al. "Critique of the two-fold measure of prediction success for ratios: application for the assessment of drug-drug interactions." Drug Metab Dispos 2011;39(2):170–173 |

The journal, year and pages match; the title does not. The paper is the source of the variable "Guest" limits
(`guest_delta`) the medium tier uses, so the citation matters.

**Question for you:** correct the title to PubMed's (the reference otherwise stands)?

## Finding 2: the medium tier's 1.5-fold limit is attributed to the EMA guideline, but no source found supports it

| | Text |
|---|---|
| **The ruleset says** (lines 39–43) | medium tier, "PBPK supports a decision together with substantial clinical evidence": AUC and Cmax `max_fold: 1.5, source: ema_pbpk_reporting` |
| **What the review found** | EMA's guideline (EMA/CHMP/458101/2016) is quoted in the literature as making acceptance criteria **depend on the regulatory impact**, with no fixed number (Paul P et al. 2025, Clin Pharmacol Ther, PMID 39748538; the ruleset's own header, lines 3–5, says the same). No paper read gave 1.5-fold as EMA's |
| **Also noted** | The high tier applies 1.25-fold to **base** AUC and Cmax. The literature applies the tight limit to the **decision metric** (e.g. the DDI ratio) and allows looser base PK: e.g. ratios within 25 % with base Cmax within 2-fold (Kuemmel C et al. 2020, CPT PSP, PMID 31652029) |

**Questions for you:**
1. Keep 1.5-fold for the medium tier, with the source changed to "platform default (SME judgement)" rather than EMA?
   Or change the number?
2. Should the high tier's 1.25-fold apply to the base PK parameters, or only to the decision metric (DDI ratios, the
   food-effect ratio, the BE ratio), with base PK looser?

## How a change is made

Per `docs/SME_SIGNOFF.md`:
- the owner approves the change in its own pull request;
- the version is bumped;
- a CHANGELOG entry names the reviewer and the date;
- the locked hashes are refreshed.

Until then the file stays `UNVERIFIED` and every report built on it says so.
