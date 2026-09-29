import os
import secrets

from fastapi import HTTPException, Request, status


async def require_device_token(request: Request) -> None:
    expected = os.environ.get("WARDEN_DEVICE_TOKEN")
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")

    if not expected or scheme.lower() != "bearer" or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid device token")
