"""
Base Repository Pattern
Abstract base for all governance repositories

Built with Pride for Obex Blackvault
"""

from abc import ABC
from typing import Generic, TypeVar, Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime

from backend.database.base import Base


T = TypeVar("T", bound=Base)


class BaseRepository(ABC, Generic[T]):
    """
    Abstract base repository implementing common CRUD operations

    Provides:
    - Standard CRUD methods
    - Error handling
    - Transaction management
    - Consistent interface across all repositories
    """

    def __init__(self, db: Session, model_class: type[T]):
        """
        Initialize repository

        Args:
            db: SQLAlchemy database session
            model_class: SQLAlchemy model class
        """
        self.db = db
        self.model_class = model_class

    def create(self, **kwargs) -> T:
        """
        Create new record

        Args:
            **kwargs: Model field values

        Returns:
            Created model instance

        Raises:
            SQLAlchemyError: On database error
        """
        try:
            instance = self.model_class(**kwargs)
            self.db.add(instance)
            self.db.commit()
            self.db.refresh(instance)
            return instance
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e

    def get(self, id: str) -> Optional[T]:
        """
        Get record by ID

        Args:
            id: Record ID

        Returns:
            Model instance or None if not found
        """
        return self.db.query(self.model_class).filter(self.model_class.id == id).first()

    def get_or_raise(self, id: str) -> T:
        """
        Get record by ID or raise exception

        Args:
            id: Record ID

        Returns:
            Model instance

        Raises:
            ValueError: If record not found
        """
        instance = self.get(id)
        if not instance:
            raise ValueError(f"{self.model_class.__name__} with id {id} not found")
        return instance

    def list(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: Optional[str] = None,
        order_desc: bool = False,
    ) -> List[T]:
        """
        List records with filtering and pagination

        Args:
            filters: Dictionary of field:value filters
            limit: Maximum number of records to return
            offset: Number of records to skip
            order_by: Field name to order by
            order_desc: Whether to order descending

        Returns:
            List of model instances
        """
        query = self.db.query(self.model_class)

        # Apply filters
        if filters:
            for field, value in filters.items():
                if hasattr(self.model_class, field):
                    query = query.filter(getattr(self.model_class, field) == value)

        # Apply ordering
        if order_by and hasattr(self.model_class, order_by):
            order_field = getattr(self.model_class, order_by)
            if order_desc:
                query = query.order_by(order_field.desc())
            else:
                query = query.order_by(order_field)

        # Apply pagination
        query = query.limit(limit).offset(offset)

        return query.all()

    def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """
        Count records matching filters

        Args:
            filters: Dictionary of field:value filters

        Returns:
            Number of matching records
        """
        query = self.db.query(self.model_class)

        if filters:
            for field, value in filters.items():
                if hasattr(self.model_class, field):
                    query = query.filter(getattr(self.model_class, field) == value)

        return query.count()

    def update(self, id: str, **kwargs) -> T:
        """
        Update record

        Args:
            id: Record ID
            **kwargs: Fields to update

        Returns:
            Updated model instance

        Raises:
            ValueError: If record not found
            SQLAlchemyError: On database error
        """
        try:
            instance = self.get_or_raise(id)

            # Update fields
            for field, value in kwargs.items():
                if hasattr(instance, field):
                    setattr(instance, field, value)

            # Update timestamp if exists
            if hasattr(instance, "updated_at"):
                instance.updated_at = datetime.utcnow()

            self.db.commit()
            self.db.refresh(instance)
            return instance
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e

    def delete(self, id: str) -> bool:
        """
        Delete record

        Args:
            id: Record ID

        Returns:
            True if deleted, False if not found

        Raises:
            SQLAlchemyError: On database error
        """
        try:
            instance = self.get(id)
            if not instance:
                return False

            self.db.delete(instance)
            self.db.commit()
            return True
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e

    def bulk_create(self, items: List[Dict[str, Any]]) -> List[T]:
        """
        Create multiple records in bulk

        Args:
            items: List of dictionaries with field values

        Returns:
            List of created model instances

        Raises:
            SQLAlchemyError: On database error
        """
        try:
            instances = [self.model_class(**item) for item in items]
            self.db.bulk_save_objects(instances, return_defaults=True)
            self.db.commit()
            return instances
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e

    def exists(self, id: str) -> bool:
        """
        Check if record exists

        Args:
            id: Record ID

        Returns:
            True if exists, False otherwise
        """
        return (
            self.db.query(self.model_class).filter(self.model_class.id == id).count()
            > 0
        )
