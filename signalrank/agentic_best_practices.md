# Code Repo Best Practices

Use this as the practical implementation checklist before adding an agentic
feature to a real codebase.

## Default Build Shape

- Start with the user workflow, success metric, and failure metric.
- Build the deterministic workflow first; add model reasoning only where input
  ambiguity, synthesis, tool choice, or recovery needs it.
- Keep the app in charge of auth, state, policy, retries, approvals, audit,
  rollout, and rollback.
- Keep the model in charge of bounded planning, extraction, synthesis, and
  explanation.
- Prefer a workflow-backed single agent before multi-agent orchestration.
- Use specialist agents only when they have separate tools, permissions, evals,
  or parallel work that justifies the extra state and latency.
- Avoid generic unrestricted tools in production paths.

## Repo Workflow

- Write or update the spec before implementing a multi-file feature.
- Add the smallest runnable slice first, then harden it with controls.
- Prefer existing local patterns, config systems, tests, and helper APIs.
- Keep prompt, policy, tool schema, eval data, and code changes reviewable as
  normal repo artifacts.
- Do not hide production behavior in unversioned config.
- Treat prompt, model, retrieval index, tool schema, and policy changes as
  release changes.
- Run the repo's standard check command before claiming completion.

## Boundaries And Authority

- Resolve identity, tenant, role, and scopes before retrieval or prompt
  construction.
- Enforce permissions in code, not in the prompt.
- Pass only the minimum context the model needs for the current step.
- Treat retrieved documents, emails, tickets, pages, and tool output as
  untrusted evidence, not instructions.
- Validate risky model proposals through policy before execution.
- Require explicit approval for external communication, production writes,
  account changes, money movement, regulated decisions, and uncertain
  high-impact actions.
- Store approval decisions as structured records, not only chat text.

## Tool Design

- Give every tool a narrow purpose and typed input/output schema.
- Keep credentials inside server-side adapters.
- Classify tools as read-only, reversible, or irreversible.
- Add idempotency keys for side-effecting tools.
- Define timeout, retry, reconciliation, and compensation behavior per tool.
- Return structured errors that the workflow can classify.
- Add contract tests for schema, auth, rate limits, and failure modes.
- Log tool proposals separately from tool execution results.

## State, Memory, And Audit

- Store workflow state in durable checkpoints; the context window is not state.
- Store side effects in an action ledger with downstream references.
- Separate session state, workflow state, tool state, approval state, memory,
  and audit.
- Add long-term memory only when it clearly improves future tasks beyond
  session state or retrieval.
- Scope memory by user and tenant, and make it correctable and deletable.
- Record evidence, prompt version, model version, policy version, tool schema
  version, state checkpoints, approvals, and side effects in audit traces.

## Retrieval And Data

- Present the long-context versus RAG tradeoff before defaulting to RAG.
- Use long context for small, stable, authorized corpora when citation and
  freshness needs are modest.
- Use RAG when knowledge is large, changing, private, permissioned, or needs
  source-level citations.
- Apply ACLs before retrieval results enter the prompt.
- Track source IDs, timestamps, freshness, deletion, and index versions.
- Measure candidate recall before tuning reranking.
- Test query rewrites for recall loss.
- Feed retrieval misses, stale answers, and conflicting-source failures into
  evals.

## Evaluation And Testing

- Build evals as the behavioral spec, not only as a final validation step.
- Separate component evals from end-to-end trajectory evals.
- Evaluate retrieval, tool choice, tool arguments, policy decisions, approval
  decisions, state transitions, cost, latency, and final output.
- Use code-based checks for deterministic properties.
- Use LLM-as-judge only with calibration against human-reviewed examples.
- Use real production patterns before synthetic eval data where possible.
- Include positive cases, refusal cases, escalation cases, adversarial cases,
  and multi-turn cases.
- Add production failures and user corrections back into the regression set.
- Run evals multiple times when non-determinism matters; track consistency, not
  only one lucky pass.

## Observability

- Trace one request across auth, policy, retrieval, model calls, tool proposals,
  approvals, tool execution, state checkpoints, final output, and feedback.
- Track infrastructure health and behavior health separately.
- Infrastructure health: uptime, HTTP errors, latency, queue depth, worker
  saturation, and dependency timeouts.
- Behavior health: groundedness, retrieval quality, tool-call accuracy,
  approval rejection rate, fallback rate, escalation rate, user corrections,
  no-progress loops, response-length drift, token drift, and cost drift.
- Attach prompt, model, retrieval-index, policy, tool-schema, and redaction
  versions to traces.
- Make failed runs easy to replay without exposing secrets or unauthorized data.

## Failure Handling

- Classify the failure before changing the prompt.
- Do not patch every bad result with a longer system prompt.
- Retry transient infrastructure failures with bounded backoff and jitter.
- Do not blindly retry hallucinated tool names, unauthorized tool proposals,
  invalid schemas, policy-blocked actions, stale-memory answers, repeated
  planner loops, or unknown side-effect states.
- Use circuit breakers around slow or failing dependencies.
- On budget exhaustion, degrade, queue, clarify, refuse, or escalate according
  to product policy.
- Route unknown side-effect status to reconciliation before trying again.
- Put exhausted or ambiguous runs into a review queue with owner and SLA.

## Cost And Latency

- Establish quality, latency, and cost baselines before optimizing.
- Attribute cost by workflow, model, tool, retrieval, retries, user segment,
  and tenant.
- Remove waste before switching to cheaper models.
- Route simple tasks away from the full agent path.
- Use smaller models for classification, extraction, and formatting.
- Reserve stronger models for ambiguous planning, synthesis, and high-risk
  review.
- Cap model calls, tool calls, retrieval tokens, wall-clock runtime, retries,
  and per-request spend.
- Move non-interactive work to async jobs.
- Run independent retrieval and tool calls in parallel when the workflow allows
  it.
- Alert on cost per task, retry cost, model-call count, response-length drift,
  and unexpected new tools or models in cost attribution.

## Rollout

- Start with offline evals against golden tasks.
- Run shadow mode before side effects.
- Use internal pilot or tenant-limited canary before broad rollout.
- Keep risky actions in approval mode until rejection and correction patterns
  are understood.
- Define rollback for prompt, model, retrieval index, policy, and tool schema
  changes.
- Release-gate quality, safety, groundedness, schema validity, latency, cost,
  answer length, tool accuracy, and approval rejection.
- Keep a behavior-health runbook, not only an infrastructure runbook.

## Code Review Checklist

- Does the model have less authority than the workflow?
- Are auth and ACLs enforced before prompt construction?
- Are all tools typed, scoped, timeout-bounded, and contract-tested?
- Are side effects idempotent and auditable?
- Is durable state separate from model context?
- Are prompts, policies, tool schemas, and evals versioned?
- Do failures map to retry, repair, clarify, escalate, compensate, or refuse?
- Are evals broad enough to catch retrieval, tool, policy, state, and output
  regressions?
- Are traces sufficient to debug both service failures and behavior failures?
- Are cost, latency, and blast-radius caps explicit?
- Is rollout staged with canary and rollback?
- Did the repo's standard test/check command pass?
