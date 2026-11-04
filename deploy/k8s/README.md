# Kubernetes status

**Status: non-operational reference manifests.**

These manifests are preserved as a historical/development reference. They are
not connected to Ajenda's release workflow and are not an authorized staging or
production deployment target.

They must not be used for a release until they meet the same contract as the
AWS ECS target and the Compose proof spine:

- role-specific immutable API, worker, assurance, migrator, and frontend images;
- current `AJENDA_*` configuration and distinct database identities;
- explicit migration completion before runtime rollout;
- schema-aware rollback/recovery;
- browser, queue, database-role, evidence, and fresh-session operator proof in
  an authorized target environment.

`deploy/scripts/rollback.sh` remains a Kubernetes reference helper only. It is
not an Ajenda production rollback mechanism. Use the CDE runbooks and target
specific controlled procedures when a target has been authorized.
