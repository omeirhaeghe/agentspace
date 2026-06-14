---
name: debugging
description: Find root causes methodically instead of guessing at fixes.
---
# Debugging

1. **Reproduce** the problem first — get a concrete failing command or input.
2. **Read the error** fully: the message, the stack trace, the line it points to.
3. **Localize** by narrowing: add prints/asserts, bisect the input, or comment out
   sections until the smallest failing case remains.
4. **Form a hypothesis**, then test it directly — don't change three things at once.
5. **Fix the cause, not the symptom.** Confirm the fix by re-running the reproduction.
6. **Check for siblings:** does the same bug exist elsewhere?

Use the `sh`/`python` tools to actually run things. If stuck after two hypotheses, step
back and question an assumption you haven't tested yet.
