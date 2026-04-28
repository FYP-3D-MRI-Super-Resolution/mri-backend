"""Base repository with common database operations."""

from typing import TypeVar, Generic, Type, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Base repository class with common CRUD operations.
    Follows Repository pattern for data access abstraction.
    """
    
    def __init__(self, model: Type[ModelType], db: Session):
        """
        Initialize repository.
        
        Args:
            model: SQLAlchemy model class
            db: Database session
        """
        self.model = model
        self.db = db
    
    def get_by_id(self, id: str) -> Optional[ModelType]:
        """
        Get entity by ID.
        
        Args:
            id: Entity identifier
            
        Returns:
            Entity or None if not found
        """
        try:
            return self.db.query(self.model).filter(self.model.id == id).first()
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e
    
    def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by=None
    ) -> List[ModelType]:
        """
        Get all entities with pagination.
        
        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            order_by: Column to order by
            
        Returns:
            List of entities
        """
        try:
            query = self.db.query(self.model)
            if order_by is not None:
                query = query.order_by(order_by)
            return query.offset(skip).limit(limit).all()
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e
    
    def create(self, entity: ModelType) -> ModelType:
        """
        Create new entity.
        
        Args:
            entity: Entity to create
            
        Returns:
            Created entity
        """
        try:
            self.db.add(entity)
            self.db.commit()
            self.db.refresh(entity)
            return entity
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e
    
    def update(self, entity: ModelType) -> ModelType:
        """
        Update existing entity.
        
        Args:
            entity: Entity to update
            
        Returns:
            Updated entity
        """
        try:
            self.db.commit()
            self.db.refresh(entity)
            return entity
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e
    
    def delete(self, entity: ModelType) -> None:
        """
        Delete entity.
        
        Args:
            entity: Entity to delete
        """
        try:
            self.db.delete(entity)
            self.db.commit()
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e
    
    def exists(self, id: str) -> bool:
        """
        Check if entity exists.
        
        Args:
            id: Entity identifier
            
        Returns:
            True if exists, False otherwise
        """
        try:
            return self.db.query(self.model).filter(self.model.id == id).first() is not None
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e
