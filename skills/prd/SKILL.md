---
name: prd
description: Write a complete PRD for a software/AI product (incl. Golden Test Cases & Local Model Requirements).
---
# Writing a PRD (software product)

When asked to write a PRD, produce a decision-grade document that includes **every section
in the template below, in this order**. Fill each one; where information is missing, write a
clearly-marked `> TODO:` rather than inventing facts, and collect those as open questions.

How to write it well:
- **Lead with the answer** in each section; cut preamble.
- **Make requirements testable** — each should be verifiable, with a priority (P0/P1/P2).
- **Quantify** — success metrics, latency, accuracy, and model specs need real numbers.
- Two sections are mandatory and often skipped — treat them as load-bearing:
  - **Golden Test Cases:** the canonical input → expected-output examples that *define*
    correct behavior. Include happy-path, edge, and failure cases; for each give the exact
    input, the expected output (or acceptance criteria), and the pass/fail rule. These are
    the regression/eval set the product is graded against — be concrete, not hand-wavy.
  - **Local Model Requirements:** everything needed to run the product's model(s) locally —
    model family & size, quantization, the minimum + recommended hardware (RAM/VRAM/CPU/GPU/
    disk), target latency & throughput, context window, runtime (e.g. Ollama / llama.cpp /
    vLLM), offline/privacy constraints, accuracy floor vs. the cloud baseline, and the
    cloud-fallback policy.
- When done, **save the PRD as a markdown file** (via `write_file`) and report the path.

---
<!-- ▼▼ This is the house template — the agent reproduces it exactly. Edit to taste. ▼▼ -->

# PRD: <Product / Feature Name>

**Author:** <name> · **Date:** <date> · **Status:** Draft · **Reviewers:** <names>

## 1. Summary
One paragraph: what we're building, for whom, and why it matters.

## 2. Problem & Context
- The problem and who has it; evidence it's real (data, quotes, support tickets).
- Why now; what changes if we don't do this.

## 3. Goals & Non-Goals
- **Goals:** target outcomes (not features).
- **Non-Goals:** explicitly out of scope for this version.

## 4. Success Metrics
The numbers that prove it worked — each with a target and how it's measured.

## 5. Users & Use Cases
Primary persona(s) and the key user stories / scenarios ("As a …, I want …, so that …").

## 6. Functional Requirements
| # | Requirement | Priority | Acceptance criteria |
|---|-------------|----------|---------------------|
| R1 | … | P0 | … |

## 7. Non-Functional Requirements
Performance, reliability, security, privacy/compliance, scalability, accessibility, cost.

## 8. Golden Test Cases
The canonical examples that define "correct." Cover happy-path, edge, and failure cases.

| # | Scenario | Input | Expected output / behavior | Pass criteria |
|---|----------|-------|----------------------------|---------------|
| G1 | happy path | … | … | … |
| G2 | edge case | … | … | … |
| G3 | failure / guardrail | … | graceful handling … | … |

> These double as the eval/regression suite — keep them precise and runnable.

## 9. Local Model Requirements
For products that run a model on-device / self-hosted.

| Aspect | Requirement |
|--------|-------------|
| Model(s) & size | e.g. Llama-3.1-8B-Instruct |
| Quantization | e.g. Q4_K_M (GGUF) |
| Min hardware | RAM / VRAM / CPU / disk to run at all |
| Recommended hardware | for the target experience |
| Latency / throughput target | e.g. < 2 s first token; ≥ 20 tok/s |
| Context window | tokens required |
| Runtime | Ollama / llama.cpp / vLLM / … |
| Offline / privacy | must run with no network? data leaves device? |
| Accuracy floor | min quality vs. the cloud baseline (tie to Golden Test Cases) |
| Cloud fallback | when/whether to fall back to a hosted model |

## 10. UX / Flow
Key screens or the step-by-step flow; link mocks/designs.

## 11. Dependencies & Integrations
Internal/external services, APIs, models, data sources, and their owners.

## 12. Risks & Open Questions
- Risks + mitigations.
- Open questions (each with an owner and needed-by date).

## 13. Rollout & Milestones
Phasing, milestones with dates, what "launched" means, and the rollback plan.

## 14. Appendix
References, prior art, glossary.

<!-- ▲▲ End house template ▲▲ -->
