# Use model semantic routing for Work Acceptance

The Voice LLM decides whether to answer, accept Work, clarify, query existing Work, or relay a permission based on the full conversation and tool contracts. We constrain this behavior with prompts, hard safety guards, and a versioned Routing Evaluation corpus rather than a deterministic keyword classifier, because fixed phrases cannot reliably distinguish discussion, reference resolution, executable requests, and delivered answers across natural speech.

## Consequences

Routing quality is model-dependent and must be release-tested against the corpus. Program code still enforces objective completeness, idempotency, Workspace Scope selection and session binding, and permission correlation, but it does not infer user intent from verb lists or regular expressions.
