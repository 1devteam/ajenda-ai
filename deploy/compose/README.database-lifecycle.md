# Database lifecycle and local Compose recovery

Ajenda separates privileged, one-time PostgreSQL provisioning from routine schema
migrations and runtime startup. The `role-bootstrap` Compose service is behind the
`bootstrap` profile and is **not** a dependency of `migrate`.

## First initialization (new PostgreSQL volume only)

1. Supply `POSTGRES_PASSWORD` and four distinct `AJENDA_*_DATABASE_PASSWORD`
   values using the selected Compose interpolation environment.
   For local Compose this is the root `.env`; for the production-like Compose
   file use `docker compose --env-file deploy/compose/.env.prod -f
   deploy/compose/docker-compose.prod.yml ...`.
   Also ensure the service `env_file` paths exist. Do not commit passwords.
2. Start `db` and wait for PostgreSQL initialization to finish.
3. Execute `docker compose --profile bootstrap run --rm role-bootstrap`
   **only** when the database is newly initialized and its privileged
   `ajenda` login is authorized. This command applies role passwords and
   transfers ownership. It is not a read-only check.
4. Start `migrate`, then the API, worker, assurance and frontend normally.

For managed PostgreSQL or hardened deployments with no privileged `ajenda`
login, use the separately authorized
`deploy/scripts/provision-database-roles.sh` once during provisioning.
Do not restore an unneeded superuser login simply to run Compose.

## Existing database / routine startup

Use the **existing** four role credentials. Start Compose normally, without the
bootstrap profile. Routine migrations run as `ajenda_migrator`. Do not regenerate
passwords: doing so in the environment alone will disconnect working services.

The PostgreSQL service uses `restart: unless-stopped`; a Docker daemon or host
restart therefore restores the existing container against its named
`postgres_data` volume. This does not run privileged bootstrap SQL or recreate
the database. After a source update that changes migrations, explicitly rebuild
the **migrate** image before bringing up dependent services, for example:

```bash
docker compose build migrate
docker compose up -d migrate api worker assurance frontend
```

The migration image must contain every revision already recorded by the
database. A migration error such as “Can't locate revision” indicates an
outdated image, not a reason to stamp, reset, or modify the persistent database.

Running containers can have valid database URLs even if the current host-side
Compose interpolation environment is incomplete. Recover the matching credentials
from the authorized secret source before invoking Compose. Do not paste or print
connection strings into shell output, CI logs or chat. Do not delete named volumes.

## Live proof

`deploy/scripts/live-runtime-proof.sh` no longer executes `compose down`.
By default it observes the existing Compose services without starting, rebuilding
or recreating containers. Set `AJENDA_PROOF_START_SERVICES=1` to permit an
explicit `compose up` (which can recreate containers if their configuration
has drifted). Set `AJENDA_PROOF_START_SERVICES=1 AJENDA_PROOF_REBUILD=1`
to additionally rebuild images. The script still executes an operator mission
and an assurance cycle when configured; these operations can change application
data. Run them against isolated infrastructure for non-disruptive verification
of a customer deployment.

For a newly created, isolated proof database, additionally set
`AJENDA_PROOF_BOOTSTRAP_ROLES=1`. This explicitly runs the bootstrap profile
before the migrator so the four restricted identities exist. Never set this
flag for an existing customer database: routine proof and service startup use
the already-provisioned credentials and do not alter role ownership or grants.

The Compose PostgreSQL healthcheck uses `pg_isready -d ajenda` without a
runtime-role username. It measures server availability, not successful role
authentication, so a fresh volume can become healthy before explicit bootstrap
and an existing hardened database does not retry the retired `ajenda` login.
Verify the application's effective database identity and migration revision
separately.

## Verification

- `docker compose config --quiet` succeeds with complete interpolation inputs.
- Existing-database startup does not run `role-bootstrap`.
- First-time provisioning creates four distinct restricted LOGIN roles.
- A migrator-authenticated migration reaches the expected Alembic revision.
- The API, worker and assurance cannot bypass RLS.
- HTTP frontend proxy and authenticated tenant requests work.
- Redis queue admission, worker consumption, and durable mission evidence pass.

Do not use `docker compose down -v` on a persistent deployment.

## Host network exposure

Both Compose definitions bind published ports to `127.0.0.1` only.
This includes the local frontend/API, local PostgreSQL/Redis, optional HubSpot
services, and production-like Prometheus/OTEL diagnostics. Docker-internal
connections still use service names and container ports without host publishing.

Use an intentionally configured reverse proxy or authenticated Cloudflare Tunnel
to publish **only the frontend ingress** if remote access is required. Do not
expose PostgreSQL, Redis, the worker, migrator, assurance, or monitoring ports.

Changing port bindings requires an explicit container recreate. Do not run
`docker compose down -v`; first verify role credentials are available to Compose
interpolation, then schedule a controlled deployment and check the host listeners.
