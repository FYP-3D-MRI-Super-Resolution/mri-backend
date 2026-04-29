"""Role-based access control helpers."""
from typing import List
from fastapi import Depends, HTTPException, status
from app.core.auth import get_current_user


def require_role(role: str):
    async def _require(current_user=Depends(get_current_user)):
        if not current_user or getattr(current_user, "role", None) != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: insufficient role",
            )
        return current_user

    return _require


def require_any_role(roles: List[str]):
    async def _require(current_user=Depends(get_current_user)):
        if not current_user or getattr(current_user, "role", None) not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: insufficient role",
            )
        return current_user

    return _require
