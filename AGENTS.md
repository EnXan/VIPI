# Repository working agreement

## Releases

- Include the version bump in the same pull request as every release-worthy
  code update; do not wait until after that update has merged. Run
  `uv version --bump patch` for a bug fix (or the appropriate minor/major bump)
  and include the resulting `pyproject.toml` and `uv.lock` changes in that PR.
  If an update has already merged without a version bump, open a follow-up
  version-only PR before tagging a release.
- Whenever the version in `pyproject.toml` changes, search documentation,
  examples, and other repository references for mentions of the previous
  version. Update references presented as current to the new version in the
  same PR; keep references that clearly document historical releases unchanged.
- After the PR containing the version bump is merged and its CI passes, check
  out the updated `main`, create an annotated tag matching the version in
  `pyproject.toml`, and push the tag. For example, for version `0.1.3`, run:

```bash
git switch main
git pull --ff-only
git tag -a v0.1.3 -m "Release v0.1.3"
git push origin v0.1.3
```

- Pushing the `v*` tag starts `.github/workflows/ci-release.yml`, which runs CI,
  builds distributions, and publishes to PyPI. A merge to `main` alone does
  not publish a release; verify the tag workflow and publication.

## Working principles

- Use English for communication, UI text, messages, code comments and project
  documentation. Preserve user-entered data, source transcripts and quoted source
  material as supplied; do not translate or rewrite them as editorial cleanup.
- Apply: **As much as necessary, as little as possible.** This applies equally to
  implementation, answers and documentation.
- Give reasoned pushback on questionable user decisions. Explain the concrete
  concern, supporting evidence and a simpler or better-supported alternative.
  Respect an explicit informed choice within the authorized task.
- Base decisions and factual claims on actual sources, preferably the user's
  supplied requirements and references. Inspect current code for implementation
  facts. Distinguish requirements, observed behavior, proposals and unverified
  assumptions. Do not invent evidence or present inference as validation.
- Base architecture and implementation on current, evidenced requirements.
  Choose the simplest solution that meets them. Do not add speculative
  abstractions, features or safeguards "just in case".

## Scope, planning and review

- Keep every temporary conversational plan, checklist, TODO or work queue under
  `.llm-plans/`. Its working files are local and ignored by Git; permanent design
  documentation belongs in `docs/` and important decisions in `adr-code/`.
- Implement one agreed concept at a time. Verify it, demonstrate the concrete
  result and validation boundary, then stop for joint review before starting
  the next concept. Record follow-up concepts in `.llm-plans/`; elapsed time or
  silence is not agreement to start them.
- Before editing, inspect `git status` and the relevant instructions and sources.
  Preserve existing work and coordinate overlapping changes. Do not combine
  unrelated cleanup with the current concept.
- Run checks appropriate to the change. Report what was actually verified and
  what remains untested; a documentation-only change does not require a full
  model run. Windows/Linux execution remains unverified until tested there.

## Contributing

- Work on a feature branch or fork, then open a pull request targeting `main`.
- Name branches with a prefix matching the change's primary purpose, followed
  by a short lowercase, kebab-case name. Use `feature/<name>` for features,
  `fix/<name>` for bug fixes and patches, `doc/<name>` for documentation-only
  changes, `refactor/<name>` for behavior-preserving refactors, `test/<name>`
  for test-only changes, `ci/<name>` for CI/CD changes, and `chore/<name>` for
  maintenance or dependency updates. Use the category prefix directly, without
  an additional generic prefix.
- Set up the development environment with
  `uv sync --extra ocr --extra detector-local --extra research --extra test`
  and run the checks relevant to your change.
- Complete the pull request template and summarize the change and validation
  performed.
- See [CONTRIBUTING.md](CONTRIBUTING.md) for contributor guidance and
  [development](docs/development.md) for setup, checks, and release instructions.

## Package management

- Use `uv` as the package manager for this project. Use `uv add` and `uv remove`
  for dependency changes, `uv sync` to provision the project environment and
  `uv run` for commands in the default environment. Keep `uv.lock` in sync.
  Use `uv pip` only for standalone requirements in separate environments, not
  project installs. When a guide names another environment, run its interpreter.

## Restrictions and decision records

- Do not introduce arbitrary limits, caps, quotas or truncation without a
  concrete, documented use case or explicit requirement. Hypothetical resource
  protection alone is insufficient justification.
- When a restriction is necessary, document its purpose, effect on normal
  operation, alternatives and tradeoffs in the relevant ADR. Distinguish actual
  model/protocol requirements from application heuristics. Existing code alone
  does not establish that an inherited restriction is justified.
- Record important implementation, code architecture and design decisions in
  `adr-code/`. Include context and sources, decision, alternatives, consequences
  and validation boundary. Record important decisions when made; avoid ADRs for
  routine edits that introduce no meaningful decision.
- When an agreed decision changes, create a replacement ADR with a summary of
  the previous ADR: its identifier, decision, rationale and reason for revision.
  Then delete the superseded ADR file. Do not delete it before carrying that
  summary forward or treat a proposal as an accepted replacement.
- See [the ADR index](adr-code/README.md) for accepted decisions. Recording an
  inherited behavior does not retroactively approve its rationale or validate it.

## Project boundaries

- Product code lives under `src/vipi/`; the public commands are `vipi setup` and
  `vipi scan`. Preserve the agreed CLI contract unless a change is agreed.
- Research UI, dataset evaluation and experiments live under `research/` and
  import `vipi`. Product code must not import research or Flask.
- Keep OCR, detection, input selection, reporting and storage responsibilities
  distinct. Reuse their existing contracts before adding new abstractions.
- Use [architecture](docs/architecture.md), [CLI usage](docs/cli.md) and
  [development](docs/development.md) for current behavior and commands.
- For OCR reference work, read [research/ocr_eval/README.md](research/ocr_eval/README.md)
  and the active catalog before changing data. Preserve source files,
  exact reference transcripts and provenance.
