from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.auth import decode_token

# Endpoint yang tidak perlu token
WHITELIST = {
    "/auth/login",
    "/login",
    "/",
    "/docs",
    "/openapi.json",
    "/openapi.json",
    "/redoc",
}

# Prefix path yang tidak perlu token (static assets + login page)
WHITELIST_PREFIXES = ("/static/", "/avatars/")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Whitelist exact match
        if path in WHITELIST:
            return await call_next(request)

        # Whitelist prefix
        if any(path.startswith(p) for p in WHITELIST_PREFIXES):
            return await call_next(request)

        # Ambil token dari header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        token = auth_header.split(" ", 1)[1]
        try:
            payload = decode_token(token)
            request.state.username = payload.get("sub")
            request.state.role = payload.get("role")
        except JWTError:
            return JSONResponse({"detail": "Token invalid atau expired"}, status_code=401)

        return await call_next(request)
