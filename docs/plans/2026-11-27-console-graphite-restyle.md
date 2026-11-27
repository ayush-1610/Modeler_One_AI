# The console's "Graphite" restyle (R1–R4)

**Status:** approved by the owner 2026-11-27 ("approved"), step by step: each step is one PR into `main` and stops for
the owner's review before the next. Decision record: `design-review/DECISIONS.md` D-I4. Parent work: the console
redesign (`docs/plans/2026-11-23-console-redesign-implementation.md`, slices 1–10 merged); this plan changes its look,
not its pages, routes or API.

## 1. What the owner chose
Picked in the Design Studio and approved on its prototype (three pages: Home, Inputs with a side panel, the campaign's
Fit tab):

| Choice | Pick |
|---|---|
| Direction | Clinical calm |
| Colours | Graphite mono: near-black `#18181B` for actions and the current choice; one blue `#2563EB` for charts, source links and the focus outline; status green, amber, red unchanged |
| Fonts | Plus Jakarta Sans (text), JetBrains Mono (identifiers) |
| Icons | the app's own set at a 1.5 stroke, missing ones drawn; no new dependency |
| Corners | 14 px panels, 10 px buttons and fields |
| Surfaces | soft shadows, hairline edges |
| Layout | a left sidebar holds search, Start from proposal, Your work and the account; no top bar |
| Text size | standard, 15 px (a per-person Compact view later) |
| Theme | light |

## 2. Steps
| Step | What | Exit |
|---|---|---|
| **R1** | The tokens (`app/styles/tokens.css`) take the Graphite values; the fonts change; corners, shadows, buttons, links, focus, running and the decision bar follow; every hard-coded navy or Plex value goes (the sign-in pages and the Keycloak theme included); the charts' palette is validated again | every page in the new colours and type; `e2e/acceptance.spec.ts` green at 1440 and 390 px; the owner's review |
| **R2** | The sidebar layout replaces the top bar: the workspace row, Start from proposal, search (⌘K), Your work with its count, the account at the foot; the page as one white rounded panel on the grey canvas with its breadcrumbs bar, notifications and Help top right; the phone menu | the same pages and checks; the keyboard path (skip link, menu) unchanged; the owner's review |
| **R3** | Icons at 1.5 stroke with the missing ones drawn (bell and others); buttons, tables (row hover, selected row), the side panel, dialogs, tabs (an underline for page tabs, the segmented control for view switches), source links in the blue | the same checks; the owner's review |
| **R4** | Accessibility over every page (contrast, targets, focus, the admin pages' signed-in audit); a screenshot gallery of every page for the owner's sign-off; the deploy plan updated (`docs/plans/2026-11-25-console-redesign-deploy.md`) | the owner's sign-off; then the deploy on the owner's go-ahead |

Later, by the owner's choice: a per-person "Compact view" switch (14 px text, tighter rows).

## 3. Rules that hold throughout
- **Tokens only.** Components keep naming tokens, never a hex value; dark mode, later, redefines the token block alone.
  Plotly takes no CSS variable, so a chart reads the token at run time or (the Data room's products) names the token's
  hex beside a comment that says so.
- **Contrast computed, not judged.** Text ≥ 4.5:1, controls and focus ≥ 3:1 (WCAG 2.2 AA); the chart palette through the
  data-viz validator. The values and ratios are in `design-review/DESIGN_SYSTEM.md` §2.
- **No science changes.** Rulesets, acceptance, MS-01, the CPF, the builder and the engine are untouched; no API change.
- **Each step is reversible alone:** one merge commit on `main` (`git revert -m 1`).

## 4. Deviations and choices made while building
- **R1** also restyles the Keycloak sign-in theme (not named in the approved step list) so the first page a person sees
  matches the app; its deploy needs `bash deploy/server/keycloak.sh theme` and a Keycloak restart. The owner approved R1
  with it (#189, 2026-11-27).
- **R2, notifications:** the product has no notification store; the bell lists what Your work lists (decisions, signatures
  and confirmations waiting on the person), the first six, with a link to all of it. A separate feed (things that
  happened, not things to do) would need the API, so it is not built.
- **R2, Search** opens its list under its button in the sidebar's top, which does not scroll (a list in the scrolling
  part would be cut off); the sidebar's top therefore always shows Start, Search and the main links.
- **R2, breadcrumbs** moved from each page's header into the page bar (they come from the address, so every page has them
  without a change to the page). Home has none, as before.
- **R4, the admin pages** cannot be opened by the development sign-in the e2e suite uses (it does not hold
  `modeler-admin`, and `auth.py` is locked). They were audited with the same checks through a local, uncommitted harness
  (a `sitecustomize` on that run's `PYTHONPATH` adding the role in its API process alone); CI checks the rest. Under
  Keycloak, `oidc-signing.spec.ts` reaches them as the owner.
- **R4, the gallery** is a private artifact with all 92 screens (46 pages × 2 widths) and a mark per screen ("Looks
  right" / "Needs a change" and a note) that this session can read back for a next round.
