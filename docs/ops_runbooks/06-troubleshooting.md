# 6. Troubleshooting

## Pods are CrashLooping

- **Check logs:** `kubectl logs <pod-name>`
- **Check events:** `kubectl describe pod <pod-name>`
- Common causes: incorrect environment variables, database connection issues, OOM kills.

## 502 Bad Gateway Errors

- This usually means the backend service is down or unreachable from the Ingress controller.
- Check that the `omnipath-backend` service and its endpoints are correctly configured.