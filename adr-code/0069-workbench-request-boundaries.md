# 0069 — Workbench request paths and error responses

Status: accepted for implementation, 2026-11-11.

## Context and sources

The open CodeQL alerts on `main` report 28 `py/path-injection` flows from
workbench evaluation requests, eight `py/stack-trace-exposure` flows from
HTTP error responses and one `js/xss-through-dom` flow through the uploaded
image's object URL. The SARIF analyses are GitHub analysis IDs 2139580470
(Python) and 2139581873 (JavaScript).

`runs.run_directory` previously rejected forward slashes and leading dots,
but did not reject Windows separators or prevent an existing symlink from
resolving outside the runs directory. Error responses converted caught
exceptions directly to strings, which can include local paths and provider
details. `chooseImage` made a navigable blob URL from a user-supplied file.

## Decision

- A run ID remains a single directory name. Reject leading dots, both path
  separators, colons (Windows drive/stream syntax) and NUL. Preserve other
  existing names, including Unicode; impose no length limit. Resolve the
  runs root and candidate and require the candidate to start with the root
  plus its separator, so symlinks to outside and sibling-prefix paths fail.
  Explicit custom runs roots remain supported.
- The affected HTTP handlers return fixed, task-specific messages and preserve
  their status codes. Log the caught exception on the server for diagnosis.
  Missing datasets still explain the download command; network failures still
  suggest checking connectivity. Detailed validation reasons are now read in
  the server log rather than the HTTP response.
- Preview uploads with `FileReader.readAsDataURL` in the existing image element.
  Do not create a navigable blob URL. Ignore a completed read if the user has
  selected another file meanwhile. Uploads and source files remain unchanged.

## Alternatives

An ASCII-only run-ID allowlist would unnecessarily reject existing names.
Checking only separators misses symlink escapes. Suppressing CodeQL findings
does not strengthen the request boundary. Returning arbitrary exception text
after removing one known directory prefix still exposes other internal details.
Explicitly typed public validation errors could preserve detailed messages,
but would require changing error contracts across curation and evaluation;
fixed messages with server diagnostics are the smaller change here.

## Consequences and validation boundary

Malformed IDs and symlinks outside the configured runs root are rejected before
run I/O. This is a local path check, not protection against another local process
replacing symlinks after validation. CLI command names and defaults, inference,
dataset contents and scoring are unchanged. Browser error messages are less
detailed; diagnostics remain available in the terminal running the workbench.

Regression tests cover invalid IDs, a symlink to a sibling-prefix directory,
custom roots and Unicode names, HTTP status codes, hidden exception details and
server logging. A JavaScript runtime check covers preview reading and stale
selection handling. Local tests do not establish Windows/Linux execution or
model accuracy; the PR's CodeQL analysis verifies the static findings.
