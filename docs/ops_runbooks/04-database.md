# Runbook: Database Management

This runbook covers essential database management tasks for the OmniPath PostgreSQL database, including backups, restores, and migrations.

## Database Backups

Regular backups are critical for disaster recovery. The repository includes a script and configuration for automated daily backups.

### Automated Backups (Kubernetes)

If you are deploying on Kubernetes, the `k8s/backup-cronjob.yaml` manifest defines a CronJob that runs daily. This job uses the `scripts/backup_db.sh` script to perform the following steps:

1.  Executes `pg_dump` to create a compressed backup of the OmniPath database.
2.  Uploads the backup file to a configured S3-compatible object store.

To use this, you must configure the `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET`, and `S3_ENDPOINT` environment variables in the CronJob manifest.

### Manual Backups (Docker Compose)

For a Docker Compose deployment, you can run the backup script manually or set up a cron job on the host machine.

```bash
# From the host machine
docker-compose -f docker-compose.production.yml exec postgres /bin/bash -c "pg_dump -U omnipath -d omnipath | gzip > /backups/omnipath_backup_$(date +%Y%m%d%H%M%S).sql.gz"
```

This will create a compressed backup file in the `postgres_backups` volume.

## Database Restores

To restore the database from a backup:

1.  **Stop Writes to the Database**: Scale down the backend application to prevent any new data from being written during the restore process.

    ```bash
    # For Kubernetes
    kubectl scale deployment omnipath-backend --replicas=0

    # For Docker Compose
    docker-compose -f docker-compose.production.yml stop backend
    ```

2.  **Transfer the Backup File**: Copy your backup file into the `postgres` container.

    ```bash
    docker cp my_backup.sql.gz <postgres_container_id>:/tmp/my_backup.sql.gz
    ```

3.  **Perform the Restore**: Exec into the `postgres` container and use `pg_restore`.

    ```bash
    docker-compose -f docker-compose.production.yml exec postgres bash

    # Inside the container
    dropdb -U omnipath omnipath
    createdb -U omnipath omnipath
    gunzip -c /tmp/my_backup.sql.gz | psql -U omnipath -d omnipath
    exit
    ```

4.  **Restart the Application**: Scale the backend application back up.

    ```bash
    # For Kubernetes
    kubectl scale deployment omnipath-backend --replicas=1

    # For Docker Compose
    docker-compose -f docker-compose.production.yml start backend
    ```

## Schema Migrations

Database schema changes are managed using **Alembic**. Migration scripts are located in the `alembic/versions` directory.

-   **To Upgrade to the Latest Version**: This should be done as part of every deployment.

    ```bash
    docker-compose -f docker-compose.production.yml exec backend alembic upgrade head
    ```

-   **To Create a New Migration**: After making changes to your SQLAlchemy models, you can automatically generate a new migration script.

    ```bash
    docker-compose -f docker-compose.production.yml exec backend alembic revision --autogenerate -m "Add new feature table"
    ```

    Always review the generated migration script before committing it.
