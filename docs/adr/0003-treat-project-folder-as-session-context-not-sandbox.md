# Treat Project Folder as session context, not a filesystem sandbox

Project Folder supplies the ACP Session's primary working directory and relative-path context. The Recipe validates and binds the selected directory to the active session, but does not implement an additional filesystem sandbox or claim that the ACP Agent can access only that directory. Codex-native sandbox configuration and current-operation permissions remain authoritative because ACP `cwd` is session context rather than an isolation primitive.

## Consequences

UI and documentation must say that Project Folder is where the Agent works, not the only folder it can access. The Recipe cannot claim hard filesystem isolation from selecting a folder alone. Adding a Recipe-owned sandbox later requires a separate architecture and compatibility decision because it would change process launch, filesystem behavior, permission expectations, and support qualification across ACP Agents.
