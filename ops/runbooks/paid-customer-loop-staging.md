# Paid Customer Loop — Staging Runbook

Prove the stranger-ready product path on Docker Compose before production cutover.

**Prerequisites:** Docker, `docker compose`, curl, Python 3.12+

---

## 1. Environment setup

```bash
cp deploy/compose/.env.staging.example deploy/compose/.env.staging
```

Compose services load `deploy/compose/.env.prod` for API/worker/migrate runtime env.
After editing `.env.staging`, sync it:

```bash
cp deploy/compose/.env.staging deploy/compose/.env.prod
```

Generate Fernet keys and set `POSTGRES_PASSWORD`:

```bash
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Edit `deploy/compose/.env.staging`:

| Variable | Staging value |
|----------|---------------|
| `AJENDA_SIGNUP_VERIFY_URL_BASE` | `http://localhost:8080/verify-email` (or your staging host) |
| `AJENDA_CORS_ALLOWED_ORIGINS` | Same origin as the customer UI |
| `AJENDA_EMAIL_PROVIDER` | `noop` for scripted proof; `resend` for real email |
| `AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN` | `true` for local proof; **`false` in production** |
| `AJENDA_WORKER_TENANT_MODE` | `multi` (required for self-serve signups) |

For real email in staging, switch to Resend:

```env
AJENDA_EMAIL_PROVIDER=resend
AJENDA_RESEND_API_KEY=re_...
AJENDA_EMAIL_FROM=Ajenda <noreply@your-staging-domain.example.com>
AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN=false
```

---

## 2. Start the stack

```bash
docker compose \
  --env-file deploy/compose/.env.prod \
  -f deploy/compose/docker-compose.prod.yml \
  up -d --build
```

| Service | URL |
|---------|-----|
| Customer UI | http://localhost:8080 |
| API (direct) | http://localhost:8000 |
| Prometheus | http://localhost:9090 |

Wait for API readiness:

```bash
curl -fsS http://localhost:8000/readiness
```

---

## 3. Automated HTTP proof

```bash
bash deploy/scripts/paid-customer-loop-staging-proof.sh
```

This script verifies:

1. Frontend serves the SPA (`GET /`)
2. `POST /v1/onboarding/signup` → `verify-email` → `promote-bootstrap-key`
3. `GET /v1/account/me`, `/usage`, `/billing`
4. Bootstrap key cannot read billing (403) before promote

Exit code `0` means the API + frontend proxy path is healthy.

### Stripe billing proof (plan sync + ability launch)

```bash
bash deploy/scripts/stripe-staging-bootstrap.sh
docker compose --env-file deploy/compose/.env.prod -f deploy/compose/docker-compose.prod.yml up -d api --force-recreate
bash deploy/scripts/stripe-billing-staging-proof.sh
```

Bootstrap will:

- Generate a local `STRIPE_WEBHOOK_SECRET` for **simulated** webhook proof (no Stripe CLI required)
- Create Ajenda Pro/Starter test prices when `STRIPE_SECRET_KEY` is a real `sk_test_*` key

The billing proof script verifies:

1. Onboarding path (same as above)
2. Signed `checkout.session.completed` webhook → tenant plan becomes `pro`
3. `POST /v1/ability-runtime/proofs/calendar-read` returns `202` (feature gate unlocked)

---

## 4. Manual UI walkthrough

1. Open http://localhost:8080/signup
2. Create an organization → check inbox (or use dev token link if exposed)
3. Complete `/verify-email` → `/promote` → `/dashboard`
4. Run `bash deploy/scripts/stripe-staging-bootstrap.sh` and restart `api` if env changed
5. Open `/billing` → start Stripe Checkout (requires real `sk_test_*` + `price_*` IDs)
6. For browser checkout, forward Stripe webhooks with Stripe CLI (see below)
7. Confirm plan updates on `/dashboard` (should show `pro`)
8. Launch a proof task on `/tasks` and confirm it queues

### Stripe CLI webhook forwarding (manual UI checkout)

Simulated webhook proof (`stripe-billing-staging-proof.sh`) does **not** require Stripe CLI.
Real browser checkout **does** — Stripe must deliver webhooks after payment:

```bash
stripe listen --forward-to localhost:8000/v1/billing/webhook/stripe
```

Copy the webhook signing secret into `STRIPE_WEBHOOK_SECRET` in `.env.staging`, sync to `.env.prod`, then restart `api`.

---

## 5. Production cutover checklist

Before switching production env to Resend + live Stripe:

- [ ] Replace placeholder `ajenda.example.com` with your real domain in `deploy/k8s/ingress.yaml`, `configmap.yaml`, and `deploy/compose/.env.prod`
- [ ] `AJENDA_SIGNUP_VERIFY_URL_BASE` points to `https://<domain>/verify-email` (same host as ingress)
- [ ] `AJENDA_CORS_ALLOWED_ORIGINS` lists `https://<domain>` only (startup rejects localhost)
- [ ] `AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN=false`
- [ ] `AJENDA_EMAIL_PROVIDER=resend` with valid `AJENDA_RESEND_API_KEY`
- [ ] Stripe live keys and price IDs configured
- [ ] Stripe webhook endpoint registered for production API URL
- [ ] Frontend image deployed (`ghcr.io/<org>/<repo>-frontend:<version>`)
- [ ] Integration test `test_paid_customer_loop_real` passes in CI

---

## 6. Teardown

```bash
docker compose \
  --env-file deploy/compose/.env.prod \
  -f deploy/compose/docker-compose.prod.yml \
  down -v
```