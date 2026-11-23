"""
Security Module for FastAPI Endpoints.

Provides:
    - X-API-Key authentication with constant-time comparison (secrets.compare_digest)
    - Production fail-closed mode when API_KEY is missing
    - Permissive local development mode when explicitly configured or unconfigured in dev
    - Configurable thread-safe in-memory rate limiting per client IP
    - Strict non-disclosure of API key values in logs
"""

import os
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_environment() -> str:
    """Returns normalized environment name (e.g. 'development', 'production')."""
    return os.getenv("ENVIRONMENT", os.getenv("ENV", "development")).strip().lower()


def is_production() -> bool:
    """Checks whether the application is running in production mode."""
    return get_environment() in ("production", "prod")


def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)) -> Optional[str]:
    """
    Enforces X-API-Key header authentication on protected routes.

    Rules:
        - In production, fails closed (HTTP 500) if API_KEY is not configured on the server.
        - When API_KEY is configured (or REQUIRE_API_KEY is true):
            * Missing X-API-Key header -> HTTP 401 Unauthorized
            * Invalid key (constant-time check) -> HTTP 403 Forbidden
            * Valid key -> Passes authentication
        - When API_KEY is unset and environment is not production:
            * Permits unauthenticated local development.
        - Never logs or exposes API key contents.
    """
    configured_key = os.getenv("API_KEY", "").strip()
    require_key = os.getenv("REQUIRE_API_KEY", "").strip().lower() in ("true", "1", "yes")

    # Fail closed in production if API_KEY is missing
    if is_production():
        if not configured_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server configuration error: API_KEY must be set in production.",
            )

    # If an API key is configured or explicitly required
    if configured_key or require_key or is_production():
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing required API key in X-API-Key header.",
            )
        # Constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(api_key, configured_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid API key.",
            )
        return api_key

    # Permissive local dev mode
    return None


class SlidingWindowRateLimiter:
    """
    Thread-safe sliding window rate limiter tracking request timestamps per client IP.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._requests = defaultdict(deque)

    def _get_client_ip(self, request: Request) -> str:
        """
        Extracts client IP from connection.
        X-Forwarded-For is ONLY trusted if TRUST_PROXIES is enabled and the immediate
        connection originates from an explicitly configured TRUSTED_PROXIES IP.
        Otherwise, the actual peer connection IP (request.client.host) is strictly enforced.
        """
        peer_ip = request.client.host if request.client else "127.0.0.1"
        trust_proxies = os.getenv("TRUST_PROXIES", "false").strip().lower() in ("true", "1", "yes")

        if trust_proxies:
            trusted_list = [p.strip() for p in os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1,testclient").split(",") if p.strip()]
            if peer_ip in trusted_list:
                forwarded = request.headers.get("x-forwarded-for")
                if forwarded:
                    return forwarded.split(",")[0].strip()

        return peer_ip

    def check(self, request: Request) -> None:
        """
        Enforces rate limits. Raises HTTP 429 when threshold exceeded.
        """
        enabled = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() in ("true", "1", "yes")
        if not enabled:
            return

        max_requests = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
        window_seconds = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

        client_ip = self._get_client_ip(request)
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            timestamps = self._requests[client_ip]
            # Prune old timestamps outside the window
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= max_requests:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: maximum {max_requests} requests per {window_seconds}s.",
                )

            timestamps.append(now)

    def reset(self) -> None:
        """Resets all tracked request records (primarily for testing)."""
        with self._lock:
            self._requests.clear()


rate_limiter = SlidingWindowRateLimiter()


def check_rate_limit(request: Request) -> None:
    """FastAPI dependency for endpoint rate limiting."""
    rate_limiter.check(request)
