# Production Startup Checklist

**Env contract:** [`docs/deployment/production-env-contract.md`](../../docs/deployment/production-env-contract.md)  
**Architecture:** [`docs/architecture/SYSTEM_ARCHITECTURE.md`](../../docs/architecture/SYSTEM_ARCHITECTURE.md)

- Secrets provisioned through runtime secret manager or Kubernetes Secret
- Stripe keys (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, price IDs) configured
- Resend email (`AJENDA_RESEND_API_KEY`, `AJENDA_EMAIL_FROM`) and `AJENDA_SIGNUP_VERIFY_URL_BASE` configured
- `AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN=false` in production
- Database reachable
- Queue reachable
- Migration job completed successfully
- API readiness green
- Worker readiness green
- Metrics scrape working
- Tracing pipeline reachable
- Rate limiting enabled
- Structured logging enabled
