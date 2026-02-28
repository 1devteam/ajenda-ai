"""
Database Query Optimization
Performance utilities for governance queries

Built with Pride for Obex Blackvault
"""

from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, Query
from typing import Dict, Any, List
import time
import logging

logger = logging.getLogger(__name__)


class QueryPerformanceMonitor:
    """
    Monitor and log slow database queries

    Usage:
        monitor = QueryPerformanceMonitor(threshold_ms=100)
        monitor.install()
    """

    def __init__(self, threshold_ms: float = 100.0):
        """
        Initialize monitor

        Args:
            threshold_ms: Log queries slower than this (milliseconds)
        """
        self.threshold_ms = threshold_ms
        self.query_stats: Dict[str, Dict[str, Any]] = {}

    def install(self):
        """Install query monitoring hooks"""

        @event.listens_for(Engine, "before_cursor_execute")
        def before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            """Record query start time"""
            conn.info.setdefault("query_start_time", []).append(time.time())

        @event.listens_for(Engine, "after_cursor_execute")
        def after_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ):
            """Log slow queries"""
            total_time = time.time() - conn.info["query_start_time"].pop()
            duration_ms = total_time * 1000

            if duration_ms > self.threshold_ms:
                logger.warning(
                    f"Slow query ({duration_ms:.2f}ms): {statement[:200]}..."
                )

                # Track stats
                query_key = statement[:100]
                if query_key not in self.query_stats:
                    self.query_stats[query_key] = {
                        "count": 0,
                        "total_time": 0,
                        "max_time": 0,
                        "statement": statement,
                    }

                stats = self.query_stats[query_key]
                stats["count"] += 1
                stats["total_time"] += duration_ms
                stats["max_time"] = max(stats["max_time"], duration_ms)

    def get_stats(self) -> List[Dict[str, Any]]:
        """
        Get query statistics

        Returns:
            List of query stats sorted by total time
        """
        stats_list = []
        for query_key, stats in self.query_stats.items():
            stats_list.append(
                {
                    "query": query_key,
                    "count": stats["count"],
                    "total_time_ms": stats["total_time"],
                    "avg_time_ms": stats["total_time"] / stats["count"],
                    "max_time_ms": stats["max_time"],
                    "statement": stats["statement"],
                }
            )

        # Sort by total time descending
        stats_list.sort(key=lambda x: x["total_time_ms"], reverse=True)
        return stats_list

    def reset_stats(self):
        """Reset query statistics"""
        self.query_stats.clear()


class QueryOptimizer:
    """
    Query optimization utilities
    """

    @staticmethod
    def add_eager_loading(query: Query, relationships: List[str]) -> Query:
        """
        Add eager loading for relationships to avoid N+1 queries

        Args:
            query: SQLAlchemy query
            relationships: List of relationship names to eager load

        Returns:
            Query with eager loading
        """
        from sqlalchemy.orm import joinedload

        for rel in relationships:
            query = query.options(joinedload(rel))

        return query

    @staticmethod
    def add_pagination(
        query: Query, page: int = 1, page_size: int = 50, max_page_size: int = 1000
    ) -> tuple[Query, Dict[str, Any]]:
        """
        Add pagination to query

        Args:
            query: SQLAlchemy query
            page: Page number (1-indexed)
            page_size: Items per page
            max_page_size: Maximum allowed page size

        Returns:
            Tuple of (paginated_query, pagination_metadata)
        """
        # Validate and cap page size
        page_size = min(page_size, max_page_size)
        page = max(1, page)

        # Get total count
        total = query.count()

        # Calculate pagination
        total_pages = (total + page_size - 1) // page_size
        offset = (page - 1) * page_size

        # Apply pagination
        paginated_query = query.limit(page_size).offset(offset)

        metadata = {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }

        return paginated_query, metadata

    @staticmethod
    def explain_query(session: Session, query: Query) -> str:
        """
        Get EXPLAIN output for query

        Args:
            session: Database session
            query: Query to explain

        Returns:
            EXPLAIN output as string
        """
        # Get compiled query
        compiled = query.statement.compile(compile_kwargs={"literal_binds": True})

        # Run EXPLAIN
        explain_query = f"EXPLAIN {compiled}"
        result = session.execute(explain_query)

        lines = []
        for row in result:
            lines.append(str(row[0]))

        return "\n".join(lines)

    @staticmethod
    def get_missing_indexes(session: Session, table_name: str) -> List[str]:
        """
        Suggest missing indexes based on query patterns

        Args:
            session: Database session
            table_name: Table to analyze

        Returns:
            List of suggested index creation statements
        """
        # This is a simplified version
        # In production, analyze pg_stat_user_tables and pg_stat_user_indexes

        suggestions = []

        # Check for foreign keys without indexes
        inspector = inspect(session.bind)
        foreign_keys = inspector.get_foreign_keys(table_name)
        indexes = inspector.get_indexes(table_name)

        indexed_columns = set()
        for idx in indexes:
            indexed_columns.update(idx["column_names"])

        for fk in foreign_keys:
            for col in fk["constrained_columns"]:
                if col not in indexed_columns:
                    suggestions.append(
                        f"CREATE INDEX idx_{table_name}_{col} ON {table_name}({col});"
                    )

        return suggestions


class ConnectionPoolMonitor:
    """
    Monitor database connection pool health
    """

    @staticmethod
    def get_pool_status(engine: Engine) -> Dict[str, Any]:
        """
        Get connection pool status

        Args:
            engine: SQLAlchemy engine

        Returns:
            Dictionary with pool statistics
        """
        pool = engine.pool

        return {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "max_overflow": pool._max_overflow,
            "pool_size": pool._pool.maxsize if hasattr(pool, "_pool") else None,
            "status": "healthy" if pool.checkedin() > 0 else "warning",
        }

    @staticmethod
    def check_pool_health(engine: Engine) -> tuple[bool, str]:
        """
        Check if connection pool is healthy

        Args:
            engine: SQLAlchemy engine

        Returns:
            Tuple of (is_healthy, message)
        """
        status = ConnectionPoolMonitor.get_pool_status(engine)

        # Check for pool exhaustion
        if status["checked_out"] >= status["size"] + status["overflow"]:
            return False, "Connection pool exhausted"

        # Check for high usage
        usage_percent = (status["checked_out"] / status["size"]) * 100
        if usage_percent > 80:
            return False, f"Connection pool usage high: {usage_percent:.1f}%"

        return True, "Connection pool healthy"


# Global monitor instance
query_monitor = QueryPerformanceMonitor(threshold_ms=100)
