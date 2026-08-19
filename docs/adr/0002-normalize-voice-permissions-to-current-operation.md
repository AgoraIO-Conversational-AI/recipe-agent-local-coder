# Normalize voice permissions to the current operation

The voice surface offers only two decisions for a Pending Permission: allow the current operation or reject the current operation. The Permission Broker maps allow only to ACP `allow_once`, and maps reject to `reject_once` or ACP `cancelled` when no one-time rejection exists. It does not read arbitrary protocol options aloud, select persistent options, or create a Gateway session-level auto-allow policy. This keeps spoken authorization direct while preventing one natural "yes" from silently expanding to later operations.

## Consequences

The v0.1 voice contract is intentionally narrower than the complete ACP permission option model. A backend that lacks `allow_once` cannot receive authorization through this voice surface and is not fully compatible with the Certified workflow. Future support for persistent or backend-specific permission choices requires a new explicit product contract rather than an implicit mapping.
