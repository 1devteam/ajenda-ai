-- Ajenda database authority bootstrap.
--
-- Run only through the authorized bootstrap script or a deployment operator.
-- PostgreSQL psql reads the role credentials from its environment, never
-- from argv, and SQL literal quoting is handled by psql (:'variable').
-- Values must not be committed, echoed, or written to logs.
\\getenv api_password AJENDA_API_DATABASE_PASSWORD
\\getenv worker_password AJENDA_WORKER_DATABASE_PASSWORD
\\getenv assurance_password AJENDA_ASSURANCE_DATABASE_PASSWORD
\\getenv migrator_password AJENDA_MIGRATOR_DATABASE_PASSWORD

DO $$
BEGIN
    -- Earlier revisions refer to this legacy no-login role.  It remains
    -- unprivileged and is never a runtime or migrator identity.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_admin') THEN
        CREATE ROLE ajenda_admin;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_migrator') THEN
        CREATE ROLE ajenda_migrator;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_api') THEN
        CREATE ROLE ajenda_api;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_worker') THEN
        CREATE ROLE ajenda_worker;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ajenda_assurance') THEN
        CREATE ROLE ajenda_assurance;
    END IF;
END
$$;

-- ALTER applies the contract to both fresh and pre-existing roles.  An
-- existing role must never retain an elevated attribute merely because it
-- predates this bootstrap script.
ALTER ROLE ajenda_admin NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
ALTER ROLE ajenda_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
ALTER ROLE ajenda_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
ALTER ROLE ajenda_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
ALTER ROLE ajenda_assurance LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;

-- Runtime roles must not inherit or SET ROLE into a previously granted group.
-- This removes every direct membership for these identities, including a
-- stale membership in the bootstrap or migrator role.
DO $$
DECLARE
    membership record;
BEGIN
    FOR membership IN
        SELECT parent.rolname AS parent_role, member.rolname AS member_role
        FROM pg_auth_members grant_map
        JOIN pg_roles parent ON parent.oid = grant_map.roleid
        JOIN pg_roles member ON member.oid = grant_map.member
        WHERE member.rolname IN ('ajenda_api', 'ajenda_worker', 'ajenda_assurance', 'ajenda_migrator')
    LOOP
        EXECUTE format('REVOKE %I FROM %I', membership.parent_role, membership.member_role);
    END LOOP;
END
$$;

ALTER ROLE ajenda_migrator PASSWORD :'migrator_password';
ALTER ROLE ajenda_api PASSWORD :'api_password';
ALTER ROLE ajenda_worker PASSWORD :'worker_password';
ALTER ROLE ajenda_assurance PASSWORD :'assurance_password';

-- Existing installations must transfer ownership before running revision 0052
-- as ajenda_migrator.  The bootstrap principal is resolved at execution time
-- so this remains correct for local PostgreSQL, RDS, and test containers.
DO $$
DECLARE
    object_name text;
BEGIN
    FOR object_name IN
        SELECT format('%I.%I', n.nspname, c.relname)
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
    LOOP
        -- Ownership of a serial/identity sequence follows its table.
        EXECUTE format('ALTER TABLE %s OWNER TO ajenda_migrator', object_name);
    END LOOP;
END
$$;
ALTER SCHEMA public OWNER TO ajenda_migrator;

DO $$
DECLARE database_name text := current_database();
BEGIN
    EXECUTE format('ALTER DATABASE %I OWNER TO ajenda_migrator', database_name);
END
$$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO ajenda_api, ajenda_worker, ajenda_assurance;
