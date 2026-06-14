---
name: code-review
description: Review code for correctness, clarity, and risk — high signal, low noise.
---
# Code review

Review in priority order and only raise findings that matter:

1. **Correctness** — bugs, wrong logic, unhandled errors, edge cases (empty, null, large,
   concurrent), off-by-one, incorrect assumptions.
2. **Security & safety** — injection, unsanitized input, secrets in code, unsafe file/shell
   operations, destructive defaults.
3. **Clarity & maintainability** — confusing names, dead code, duplication, missing structure.
4. **Reuse & simplicity** — an existing helper that should be used, a simpler approach.

For each finding: name the file/line, explain *why* it's a problem, and suggest a fix.
Distinguish must-fix from nice-to-have. Don't nitpick style a formatter would handle, and
acknowledge what's done well.
