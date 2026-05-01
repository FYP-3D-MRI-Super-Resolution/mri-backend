"""
Authentication routes (Controller layer).
Handles HTTP requests and delegates business logic to AuthService.
Follows SOLID principles - Single Responsibility (routing only).
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from ..models import User
from ..schemas import UserCreate, UserResponse, UserLogin, Token
from app.core.auth import get_current_user
from ..services.auth_service import AuthService
from app.core.constants import APIEndpoints, EndpointDocs

router = APIRouter(prefix=APIEndpoints.AUTH_PREFIX, tags=["Authentication"])


@router.post(
    APIEndpoints.AUTH_REGISTER,
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary=EndpointDocs.AUTH_REGISTER_SUMMARY,
    description=EndpointDocs.AUTH_REGISTER_DESC
)
async def register(
    user_data: UserCreate,
    db: Session = Depends(get_db)
) -> UserResponse:
    """
    Register a new user.
    
    Args:
        user_data: User registration data
        db: Database session
        
    Returns:
        Created user information
        
    Raises:
        ResourceAlreadyExistsException: If email already registered
    """
    auth_service = AuthService(db)
    user = auth_service.register_user(user_data)
    return user


@router.post(
    APIEndpoints.AUTH_LOGIN,
    response_model=Token,
    summary=EndpointDocs.AUTH_LOGIN_SUMMARY,
    description=EndpointDocs.AUTH_LOGIN_DESC
)
async def login(
    user_data: UserLogin,
    db: Session = Depends(get_db)
) -> Token:
    """
    Login user and return access token.
    
    Args:
        user_data: User login credentials
        db: Database session
        
    Returns:
        Access token and token type
        
    Raises:
        UnauthorizedException: If credentials are invalid
    """
    auth_service = AuthService(db)
    user, access_token = auth_service.authenticate_user(user_data)
    
    return Token(access_token=access_token, token_type="bearer")


@router.get(
    APIEndpoints.AUTH_ME,
    response_model=UserResponse,
    summary=EndpointDocs.AUTH_ME_SUMMARY,
    description=EndpointDocs.AUTH_ME_DESC
)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
) -> UserResponse:
    """
    Get current user information.
    
    Args:
        current_user: Authenticated user from token
        
    Returns:
        Current user information
    """
    return current_user
