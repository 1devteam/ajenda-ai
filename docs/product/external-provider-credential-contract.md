# External Provider Credential Contract

This contract defines how future external providers reference credentials.

It does not add live providers, store plaintext secrets, decrypt credentials, call external APIs, or change runtime execution authority.

## Rules

- Credentials must be tenant-scoped.
- Manifests and action inputs must not contain plaintext secrets.
- Provider adapters may receive only credential references.
- Secret material must be resolved by runtime infrastructure or a future credential resolver.
- Provider-specific adapters must document required scopes.
- Rotation must be supported unless explicitly proven unnecessary.

## Supported reference kinds

- `env_var`
- `secret_manager`
- `k8s_secret`
- `oauth_token_store`

## Initial provider targets

- Google Calendar
- Gmail
- GitHub
- CRM
- Browser
- MCP

## Non-goals

This contract does not implement:

- Google Calendar API calls
- OAuth token refresh
- database credential storage
- secret decryption
- role orchestration
- runtime tool execution changes
