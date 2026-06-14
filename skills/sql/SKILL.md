---
name: sql
description: Write correct, readable SQL and reason about query results.
---
# SQL

1. **Know the schema** before querying: tables, columns, types, and how they join.
2. **Start small:** `SELECT … LIMIT 5` to see real rows before writing aggregates.
3. **Be explicit:** name columns (avoid `SELECT *` in final queries), qualify joins, and
   state the grain (one row per what?).
4. **Mind the traps:** `NULL` in filters and aggregates, `JOIN` fan-out double-counting,
   `GROUP BY` vs. window functions, integer division.
5. **Verify counts** before and after joins to catch accidental row multiplication.
6. Format queries readably (one clause per line) and explain what each query returns.

Prefer a couple of simple, checkable queries over one giant nested statement.
