"""Authentication service for business logic."""

import uuid
from sqlalchemy.orm import Session
from typing import Tuple

from ..models import User
from ..schemas import UserCreate, UserLogin
from app.core.auth import get_password_hash, verify_password, create_access_token
from ..repositories.user_repository import UserRepository
from app.core.constants import ErrorMessages
from app.shared.utils.exceptions import (
    ResourceAlreadyExistsException,
    UnauthorizedException,
    ResourceNotFoundException
)


class AuthService:
    """
    Service handling authentication business logic.
    Follows Single Responsibility Principle - only handles auth operations.
    """
    
    def __init__(self, db: Session):
        """
        Initialize authentication service.
        
        Args:
            db: Database session
        """
        self.db = db
        self.user_repository = UserRepository(db)
    
    def register_user(self, user_data: UserCreate) -> User:
        """
        Register a new user.
        
        Args:
            user_data: User registration data
            
        Returns:
            Created user
            
        Raises:
            ResourceAlreadyExistsException: If email already exists
        """
        try:
            # Check if user already exists
            if self.user_repository.email_exists(user_data.email):
                raise ResourceAlreadyExistsException(
                    "User", "email", user_data.email
                )
            
            # Create new user
            user = User(
                id=str(uuid.uuid4()),
                email=user_data.email,
                name=user_data.name,
                hashed_password=get_password_hash(user_data.password)
            )
            
            return self.user_repository.create(user)
        
        except ResourceAlreadyExistsException:
            raise
        except Exception as e:
            raise Exception(f"Failed to register user: {str(e)}")
    
    def authenticate_user(self, user_data: UserLogin) -> Tuple[User, str]:
        """
        Authenticate user and generate access token.
        
        Args:
            user_data: User login credentials
            
        Returns:
            Tuple of (User, access_token)
            
        Raises:
            UnauthorizedException: If credentials are invalid
        """
        try:
            # Find user by email
            user = self.user_repository.get_by_email(user_data.email)
            
            if not user:
                raise UnauthorizedException(ErrorMessages.INVALID_CREDENTIALS)
            
            # Verify password
            if not verify_password(user_data.password, user.hashed_password):
                raise UnauthorizedException(ErrorMessages.INVALID_CREDENTIALS)
            
            # Generate access token
            access_token = create_access_token(data={"sub": user.id})
            
            return user, access_token
        
        except UnauthorizedException:
            raise
        except Exception as e:
            raise Exception(f"Authentication failed: {str(e)}")
    
    def get_user_by_id(self, user_id: str) -> User:
        """
        Get user by ID.
        
        Args:
            user_id: User identifier
            
        Returns:
            User object
            
        Raises:
            ResourceNotFoundException: If user not found
        """
        try:
            user = self.user_repository.get_by_id(user_id)
            if not user:
                raise ResourceNotFoundException("User", user_id)
            return user
        except ResourceNotFoundException:
            raise
        except Exception as e:
            raise Exception(f"Failed to get user: {str(e)}")
