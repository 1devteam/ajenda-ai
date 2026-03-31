# Deployment

1. Build immutable images for api, worker, and migrate.
2. Apply namespace, configmap, and secret manifests.
3. Run migration job.
4. Deploy api and worker workloads.
5. Verify readiness and health probes.
6. Verify metrics and tracing endpoints.
