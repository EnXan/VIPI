# ADR 0006: Apache License 2.0

Status: Accepted. Recorded: 2026-10-19.

## Context and sources

The user chose full Open Source and explicitly selected Apache License 2.0
after comparing it with MIT. The [Apache License 2.0 text](https://www.apache.org/licenses/LICENSE-2.0.txt)
allows commercial use, modification and redistribution, and includes an
explicit contributor patent license. The [Open Source Initiative definition](https://opensource.org/osd)
requires open-source licenses not to restrict fields of endeavor.

The repository includes third-party models, dependencies, datasets and assets.
Their licenses are not replaced by VIPI's project license.

## Decision

License VIPI's original code, documentation and project assets under Apache
License 2.0. Include the canonical license text in the repository, identify the
project license as `Apache-2.0` in Python package metadata, include the license
in distributions, and link it from the README. Third-party material remains
under its respective license and notices.

## Alternatives

MIT is shorter and also permits commercial reuse, but has no explicit patent
grant. A source-available restriction would conflict with the user's decision
to go fully Open Source. Leaving the project unlicensed would grant no general
reuse permissions.

## Consequences

Users may use VIPI commercially, modify it, redistribute it and build competing
products. Redistributors must satisfy Apache 2.0's notice and attribution terms.
The license grants no trademark rights. Patent rights and termination are
governed by the license text.

## Validation boundary

The repository license text is taken from the Apache Software Foundation's
official version 2.0 text. This change records the intended license for
first-party VIPI code, documentation and project assets; it does not audit every
dependency, model, dataset or other third-party material for compatibility or
license completeness.
