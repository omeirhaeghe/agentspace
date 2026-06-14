---
name: coding
description: Write clean, working code that matches the surrounding style.
---
# Coding

When writing or changing code:

1. **Read first.** Inspect nearby files to match naming, structure, imports, and idioms
   before adding anything. Reuse existing helpers instead of reinventing them.
2. **Smallest change that works.** Prefer minimal, targeted edits over rewrites.
3. **Make it runnable.** Keep code syntactically valid and importable at every step;
   handle the obvious error cases.
4. **No stray output.** Don't leave debug prints or commented-out code behind.
5. **Verify.** Run the file/tests (via the `sh` or `python` tool) and report what you saw.

State assumptions explicitly when requirements are ambiguous, and prefer the boring,
readable solution over a clever one.
