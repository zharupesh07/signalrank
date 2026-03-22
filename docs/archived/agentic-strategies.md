# Agentic Coding Strategies

## Top 5 Frameworks (2026)

### 1. GSD — Get Shit Done
Fights "context rot" via spec-driven development with phased fresh context windows.
- Phases: research → plan → execute → verify
- Sub-agents commit atomically and auto-advance through milestones
- Links: [GitHub](https://github.com/gsd-build/gsd-2) | [Explainer](https://hoangyell.com/get-shit-done-explained/)

### 2. RALPH Loop
Autonomous agent loop that runs until all PRD items are complete. Uses **git as memory** instead of maintaining context.
- Pairs well with GSD (GSD manages spec/phases, RALPH handles the loop)
- Link: [GitHub](https://github.com/snarktank/ralph)

### 3. BMAD — Breakthrough Method for Agile AI-Driven Development
Orchestrates 12+ specialized agents (PM, Architect, Dev, QA) across an agile workflow.
- Best for complex enterprise products
- Link: [Overview](https://www.vibesparking.com/en/blog/ai/2026-01-25-spec-driven-development-frameworks-bmad-gsd-ralph/)

### 4. SPARC 2.0
Agentic code analysis + generation framework. Analyzes codebase deeply before writing.
- Best when understanding existing code before generating matters

### 5. Spec-Driven Development (SDD)
Methodology underlying GSD, BMAD, and others. Write spec/PRD first → generate tasks → agents execute against spec as ground truth.
- Prevents scope creep and hallucination drift across multi-session runs

## Recommended Combo for Claude Code
**GSD + RALPH** — GSD manages the spec and phases, RALPH handles the autonomous loop with git as memory.
