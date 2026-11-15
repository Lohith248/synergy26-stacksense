"""q3 item 3: database-engine vocabulary follows the chosen database.

Replication, backup and time-partitioning wording is engine-specific; a stack whose database is SQL Server, MySQL or MongoDB never gets
PostgreSQL-only terms (streaming replication, WAL, BRIN), and the reverse. Terms are from the vendors' own pages (opened 15 Nov 2026):
SQL Server editions page (sqlserver-editions: log shipping, Always On availability groups on Enterprise, Basic availability groups on
Standard with two replicas and one database, table partitioning and columnstore in every edition); MySQL 8.4 manual (replication from
the source's binary log to replicas; RANGE partitioning, mysql-partitioning); MongoDB manual (replica sets with automatic failover; the
primary records changes in the oplog).
"""

PG = ("postgresql", "supabase")


def family(db_id):
    """'pg', 'sqlserver', 'mysql', 'mongodb' or 'other'."""
    if db_id in PG:
        return "pg"
    return db_id if db_id in ("sqlserver", "mysql", "mongodb") else "other"


def standby(db_id):
    """How a self-run standby server is kept in step with the primary, for the on-premise HA sentence."""
    return {"pg": "streaming replication, continuous WAL archiving",
            "sqlserver": "an Always On availability group (a Basic availability group on Standard edition: two replicas, one database) "
                         "or log shipping, full and transaction-log backups",
            "mysql": "binary-log replication to the standby (a replica of the source), regular binary-log backups",
            "mongodb": "a replica set (the standby is a secondary that takes over automatically), regular backups"}.get(
        family(db_id), "the database's own replication to the standby, continuous log backups")


def rpo(db_id):
    """The replication and log-backup clause of RPO_NEEDS_REPLICATION."""
    return {"pg": "configure streaming replication to a standby server and continuous WAL archiving",
            "sqlserver": "configure an Always On availability group (Basic on Standard edition) or log shipping to a standby server, "
                         "with frequent transaction-log backups",
            "mysql": "configure binary-log replication to a standby replica and keep binary-log backups",
            "mongodb": "run a replica set with a secondary on a standby server"}.get(
        family(db_id), "configure the database's own replication to a standby server and continuous log backups")


def replica(db_id):
    """'a streaming replica' and its equivalents, for the single-site availability sentence."""
    return {"pg": "a streaming replica", "sqlserver": "an availability-group or log-shipping secondary",
            "mysql": "a binary-log replica", "mongodb": "a replica-set secondary"}.get(family(db_id), "a replica")


def time_partitions(db_id):
    """(component text, source ids) for time-partitioned storage on a relational database."""
    f = family(db_id)
    if f == "sqlserver":
        return "monthly partitioned tables with a clustered columnstore index", ["sqlserver-editions"]
    if f == "mysql":
        return "monthly RANGE partitions on the timestamp column", ["mysql-partitioning"]
    if f == "pg":
        return "native monthly partitions + BRIN index on the timestamp", ["postgres-partitioning"]
    return "monthly partitions on the timestamp", []


def rls_source(db_id):
    """The source for database row-level security on this engine."""
    return {"sqlserver": "sqlserver-editions"}.get(db_id, "postgres-rls")
