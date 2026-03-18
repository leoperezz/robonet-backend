from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.firebase import verify_token
from app.logger import get_logger

security = HTTPBearer()
logger = get_logger(__name__)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Extrae y verifica el Firebase ID Token del header Authorization: Bearer <token>.
    Devuelve el decoded token (contiene uid, email, etc.).
    """
    try:
        user = verify_token(credentials.credentials)
        return user
    except ValueError as exc:
        logger.warning("Auth failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
