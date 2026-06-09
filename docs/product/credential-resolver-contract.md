# Credential Resolver Contract

The Credential Resolver Contract defines the runtime-only boundary for turning an `ExternalCredentialReference` into credential material for external provider adapters.

## Scope

This phase adds only the resolver contract.

It does not:

- store credentials
- decrypt secrets
- refresh OAuth tokens
- import Google SDKs
- call external APIs
- change `tool.invoke`
- change provider selection
- wire live providers into runtime

## Flow

```text
ExternalCredentialReference
→ CredentialResolver
→ ResolvedExternalCredential
→ provider adapter
