"""
Base repository with common database operations.

Generic CRUD layer.  All concrete repositories extend this class.
Follows the Repository pattern for data-access abstraction and keeps
business logic out of ORM queries.
"""

from typing import TypeVar, Generic, Type, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic repository providing common CRUD operations.

    Follows the Repository pattern: callers interact with domain objects
    and are shielded from SQLAlchemy internals.
    """

    def __init__(self, model: Type[ModelType], db: Session) -> None:
        """
        Initialise the repository.

        Args:
            model: SQLAlchemy model class managed by this repository.
            db:    Active database session.
        """
        self.model = model
        self.db = db

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def get_by_id(self, id: str) -> Optional[ModelType]:
        """
        Return a single entity by primary key, or *None* if not found.

        Args:
            id: Primary-key value (string UUID).

        Returns:
            Matching entity or None.
        """
        try:
            return self.db.query(self.model).filter(self.model.id == id).first()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise exc

    def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by=None,
    ) -> List[ModelType]:
        """
        Return all entities with optional pagination and ordering.

        Args:
            skip:     Number of records to skip.
            limit:    Maximum records to return.
            order_by: SQLAlchemy column expression to order by.

        Returns:
            List of entities.
        """
        try:
            query = self.db.query(self.model)
            if order_by is not None:
                query = query.order_by(order_by)
            return query.offset(skip).limit(limit).all()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise exc

    def exists(self, id: str) -> bool:
        """
        Check whether an entity with the given primary key exists.

        Args:
            id: Primary-key value.

        Returns:
            True if the entity exists, False otherwise.
        """
        try:
            return (
                self.db.query(self.model).filter(self.model.id == id).first()
                is not None
            )
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise exc

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def create(self, entity: ModelType) -> ModelType:
        """
        Persist a new entity to the database.

        Args:
            entity: Unsaved ORM instance.

        Returns:
            Saved and refreshed entity.
        """
        try:
            self.db.add(entity)
            self.db.commit()
            self.db.refresh(entity)
            return entity
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise exc

    def update(self, entity: ModelType) -> ModelType:
        """
        Commit pending changes on an already-tracked entity.

        Args:
            entity: Dirty ORM instance.

        Returns:
            Refreshed entity.
        """
        try:
            self.db.commit()
            self.db.refresh(entity)
            return entity
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise exc

    def delete(self, entity: ModelType) -> None:
        """
        Delete an entity from the database.

        Args:
            entity: ORM instance to remove.
        """
        try:
            self.db.delete(entity)
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise exc
