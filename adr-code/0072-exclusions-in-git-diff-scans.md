# ADR 0072: User exclusions in Git diff scans and the GitHub Action

Status: Accepted, 2026-11-12.

## Context and sources

Filesystem scans apply ordered user rules from a `.vipiignore` file and
repeatable `--exclude` options
([`inputs/exclusions.py`](../src/vipi/inputs/exclusions.py),
[`inputs/files.py`](../src/vipi/inputs/files.py),
[CLI usage](../docs/cli.md#excluding-images)). File rules come
first, command-line rules follow and the last matching rule wins.

Diff scans ([`inputs/git.py`](../src/vipi/inputs/git.py)) read added, modified
and type-changed images from Git objects between the merge base and `HEAD`.
They do not read the worktree: uncommitted edits and missing worktree files do
not matter. `select_images` rejects `--exclude` and any `.vipiignore` in the
repository when `diff` is set. The GitHub Action ([`action.yml`](../action.yml))
uses diff scans for pull requests, so a repository with a `.vipiignore` cannot
use the Action on PRs at all, and the Action has no input for exclusions.
Requested in [issue #66](https://github.com/EnXan/VIPI/issues/66).

The rules decide which images are scanned. In a PR scan the head commit is
written by the PR author, so a rule file read from `HEAD` would let a PR exempt
the images it adds.

## Decision

- **Rule file source.** Diff scans read `.vipiignore` from the repository root
  of the resolved base commit (the `--diff` reference), via
  `git cat-file`, not from the worktree or `HEAD`. A missing file means no file
  rules. A change to `.vipiignore` takes effect for diff scans once it is on
  the base branch. Read or parse errors fail the scan, as for filesystem scans.
- **Command-line rules.** `--exclude` is allowed with `--diff` and follows the
  file rules, with the same last-match precedence.
- **Syntax and root.** Unchanged: the existing rule subset, matched against the
  path relative to the repository root.
- **Matching.** Each changed image path is decided on its own path. This gives
  the same result as the filesystem walk, which prunes a directory only when no
  later `!` rule could re-include a descendant. It needs no worktree file, so
  images missing from the worktree, renames (deletion plus addition) and
  deleted images (not selected) need no special handling. Explicit scope paths
  restrict the selection as before and do not bypass rules.
- **Report.** Excluded images are listed as skipped with reason
  `excluded_by_user`, the rule, the source (`<reference>:.vipiignore` or the
  command line) and the line or argument number. Diff scans list each excluded
  file; they do not report pruned directories. An all-excluded selection scans
  nothing and exits 0, like an empty diff.
- **Action.** A new `exclude` input takes newline-separated rules and passes
  them as `--exclude` to both the selection step and the scan, so model setup
  and scanning use the same rules. For PR events the rule file comes from the
  PR's base branch, which the Action already uses as the diff reference.
- Exit codes are unchanged.

## Alternatives and consequences

- **Read `.vipiignore` from `HEAD`.** Lets a branch adjust its own rules
  immediately, but a PR could exempt its own images. Rejected.
- **Read it from the merge base.** Also not PR-controlled, but ignores rule
  changes merged into the base branch after the branch was created. The base
  tip is what the target branch currently enforces.
- **Read it from the worktree.** Contradicts the committed-bytes contract of
  diff scans and depends on what is checked out.
- **Keep rejecting exclusions.** Repositories with a `.vipiignore` cannot use
  PR scans.

Consequences: a PR that changes `.vipiignore` is scanned with the old rules;
the change applies after merge. The `exclude` input lives in the workflow file,
which a `pull_request` event takes from the PR itself; base-branch rules only
protect the rule file, not the workflow. Under `pull_request_target` both come
from the base branch. Locally, `vipi scan --diff origin/main` uses the rules of
`origin/main`, so fetch it first.

## Validation boundary

Covered by integration tests with Git fixture repositories
(`tests/integration/test_vipi_cli.py`):

- Base rules exclude an added image; a `.vipiignore` added or changed only on
  the branch has no effect.
- Ordered `!` re-inclusion, directory rules, `--exclude` after file rules.
- Renamed image matched on its new path; deleted image not selected; image
  missing from the worktree still selected or excluded by its committed path.
- All images excluded: nothing scanned, exit 0, skip reasons in the report.
- Invalid or symlinked base rule file fails the scan.

Not tested: the composite Action itself is not run in tests; that selection and
scan receive the same rules is checked by reading `action.yml`. A base rule
file in a non-UTF-8 encoding fails with a read error but has no dedicated test.
