"""
Authentication endpoints
/api/auth/signup
/api/auth/login
"""
from fastapi import APIRouter, HTTPException, status

from backend.models.schemas import SignupRequest, LoginRequest, TokenResponse
from backend.core.database import db
from backend.utils.auth import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse)
def signup(request: SignupRequest):
    """
    Create a new user account
    """
    # Check if user already exists
    existing_user = db.get_user(request.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )

    # Validate and create user
    try:
        password_hash = hash_password(request.password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    success = db.create_user(request.username, password_hash, request.role)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user"
        )

    # Return access token
    access_token = create_access_token(request.username, request.role)
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest):
    """
    Login with username and password
    """
    # Get user
    user = db.get_user(request.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    # Verify password
    if not verify_password(request.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    # Return access token
    access_token = create_access_token(user["username"], user["role"])
    return TokenResponse(access_token=access_token)
