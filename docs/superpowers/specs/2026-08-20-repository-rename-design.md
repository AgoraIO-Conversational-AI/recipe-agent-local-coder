# Repository Rename Design

**Date:** 2026-08-20

## Decision

Rename the repository from `recipe-agent-acp-local` to
`recipe-agent-local-coder`.

The new name keeps the Agora `recipe-agent-*` convention, describes the
user-facing purpose, and does not bind the recipe to ACP or to one coding-agent
implementation.

## Scope

The rename updates:

- the GitHub repository name;
- the local checkout directory;
- the `origin` remote URL;
- current package, contributor, MCP server, repo-card, and maintained
  documentation identifiers;
- current clone URLs and repository links that would otherwise rely on GitHub
  redirects.

The rename does not change:

- runtime behavior, routes, ports, environment variables, or commands;
- the `acp-local` recipe role or ACP architecture terminology where it
  describes the implementation;
- historical design documents, plans, research reports, Git commits, or
  evidence whose old name is part of the historical record;
- the upstream `agent-quickstart-python` remote.

## Execution Order

1. Update current repository identifiers and maintained documentation locally.
2. Verify that the old identifier remains only in intentionally historical
   material.
3. Run the relevant offline checks and commit the rename.
4. Rename the GitHub repository, relying on GitHub's redirect for existing
   links.
5. Update `origin`, push the rename commit, stop the local development process,
   and rename the checkout directory.
6. Verify the new local path, remote identity, clean worktree, and local startup
   without starting an Agora conversation.

## Failure Handling

If the GitHub rename fails, keep the local checkout at its original path and do
not change `origin`. If the GitHub rename succeeds but a later local step fails,
use the new GitHub URL as the source of truth and repair the local checkout and
remote without reverting repository history.

## Acceptance

- GitHub resolves `AgoraIO-Conversational-AI/recipe-agent-local-coder`.
- The checkout is `/Users/zhangqianze/Documents/recipe-agent-local-coder`.
- `origin` uses the new repository URL and the feature branch is synchronized.
- Current package and maintained documentation identifiers use the new name.
- Offline verification passes and no Agora conversation is started.
