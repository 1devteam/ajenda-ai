# 4. Database Management

## Backups

Database backups are performed automatically every 24 hours by a Kubernetes CronJob. The backup script (`scripts/backup_db.sh`) dumps the database, compresses it, and uploads it to a configured S3 bucket.

## Restores

To restore from a backup:

1.  **Download the backup** from the S3 bucket.
2.  **Scale down the backend** to 0 replicas to prevent writes:
    ```bash
    kubectl scale deployment omnipath-backend --replicas=0
    ```
3.  **Exec into the PostgreSQL pod** and use `pg_restore` to load the backup file.
4.  **Scale the backend up** to its original replica count.