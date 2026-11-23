# Archive of the frontend before the redesign (Phase 9)

Made 2026-11-23 16:01 UTC, before any production change of the redesign (charter Phase 9, "Mandatory archive
procedure"). Nothing was switched, discarded or overwritten.

## What was preserved
| Layer | Where | What |
|---|---|---|
| Git tag | `pre-aws-redesign-20261123-1601` (annotated) | Commit `49907a6733ba40970db4c14c1d4f2c83ea774bb7` on `claude/inspiring-einstein-191gn3`: the whole repository as approved through Gate 4, including the 2026-11-23 security fixes (R-S01, R-S03, R-S04) |
| Git branch | `archive/stylish-frontend-20261123-1601` | Points at the same commit. Created without switching the active branch |
| Files | `design-review/archive/stylish-frontend/apps/web/` | All 292 files of `apps/web` (tracked plus untracked-not-ignored; there were no untracked or uncommitted files): `app/` (routes, layout, 20 stylesheets, fonts, icon), `components/`, `lib/`, `e2e/` (54 specs and fixtures), `package.json`, `package-lock.json`, `next.config.mjs`, `proxy.ts`, `server.mjs`, `tsconfig.json`, `playwright.config.ts` |
| Contract | `design-review/archive/stylish-frontend/_support/openapi.json` | The API contract the archived types were generated from (`npm run typecheck` checks `lib/api-types.ts` against it) |

Not copied (rebuilt from the above): `node_modules/`, `.next/`, `test-results/` (all git-ignored).

**State at archive time:** working tree clean, no stash, one worktree, no untracked files under `apps/web`. Branches:
`main` (`61ffb53`) and `claude/inspiring-einstein-191gn3`. `main` does not contain this baseline yet: the session
branch holds two commits of another session (`445fb51`, `cf3f6ec`) and the redesign work since.

## Verified recoverable (2026-11-23)
1. **Identical to the tag:** `git archive pre-aws-redesign-20261123-1601 apps/web` extracted and compared with
   `diff -r` against the archive folder: no difference. The contract copy is byte-identical (`cmp`).
2. **Restore drill:** the archive copied into an empty folder laid out as the repository (`apps/web`,
   `docs/api/openapi.json`), then `npm ci` from the archived lockfile, `npm run typecheck` (exit 0) and `npm run build`
   (exit 0, "Compiled successfully", 16 static pages). The drill folder was deleted afterwards.
3. **Repository checks with the archive present:** `ruff check .` passes, the architecture tests pass (183). Pytest does
   not collect the archive (its `testpaths` are fixed), and the web build does not include it.

## How to restore
Whole frontend, from git (preferred):
```bash
git checkout pre-aws-redesign-20261123-1601 -- apps/web
```
Whole frontend, from the file archive (if git history is unavailable):
```bash
rm -rf apps/web && cp -rp design-review/archive/stylish-frontend/apps/web apps/web && cp design-review/archive/stylish-frontend/_support/openapi.json docs/api/openapi.json
```
Then `npm --prefix apps/web ci`, `npm --prefix apps/web run typecheck`, `npm --prefix apps/web run build`.

One file or folder (for example the old dashboard):
```bash
git checkout pre-aws-redesign-20261123-1601 -- apps/web/components/dashboard
```
A deployed server rolls back by deploying the tag's tree: check out the tag in a clean clone and run
`bash deploy/dev/deploy_to_server.sh` (CLAUDE.md: deploy only from a checkout of `main`, so the rollback is merged to
`main` first, or the owner approves a one-off deploy of the tag).

## Limitations
- The tag and the archive branch are **local to this cloud session until pushed**. The file archive is committed and
  pushed with the session branch, so it survives the container; the tag and branch need the owner's go-ahead to push
  (they are new refs on the shared remote).
- The archive holds the frontend only. The API is unchanged by the redesign except for the backend changes listed in
  `BACKEND_CHANGE_REQUIREMENTS.md`; each of those is its own commit and is reverted on its own.
- The archive reflects this session branch, not `main`. If `main` moves before the redesign lands, the implementation
  plan's first step merges `main` into the work branch; the baseline stays this tag.
