"""Minimal single-tenant OAuth authorization server, wrapping the one static
MCP_HTTP_TOKEN bearer secret in OAuth's shape.

Needed because ChatGPT's custom-connector setup only offers "No auth" or
OAuth for an MCP server - there's no way to hand it a plain bearer token
directly. This deployment has no real user base (every caller gets the same
tool access the static token already grants), so /authorize auto-approves
with no login screen, and every issued access_token is literally the
configured MCP_HTTP_TOKEN value. This is NOT per-client/per-user auth - it's
an OAuth-shaped wrapper around the same single shared secret, wired up so
OAuth-only clients (like ChatGPT) can reach it. Registered clients and
issued codes live in memory only, which is fine for a single-instance
Railway service: a restart just means any in-flight authorize/token
exchange must be redone.

PKCE verification, redirect_uri matching, code expiry, and dynamic client
registration bookkeeping are all handled generically by the `mcp` SDK's
built-in auth routes/handlers (mcp.server.auth.handlers) before they ever
call into this provider - this class only needs to persist the few records
those handlers ask it to.
"""

import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

_CODE_TTL_SECONDS = 600


class SingleTokenOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, token: str) -> None:
        self._token = token
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._codes: dict[str, AuthorizationCode] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self._clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        code = secrets.token_urlsafe(32)
        self._codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + _CODE_TTL_SECONDS,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
        )
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self._codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        self._codes.pop(authorization_code.code, None)  # single-use
        return OAuthToken(access_token=self._token, token_type="Bearer")

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None  # never issued - the access token above never expires

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        raise TokenError(error="unsupported_grant_type", error_description="Refresh tokens are not issued.")

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token != self._token:
            return None
        return AccessToken(token=token, client_id="static", scopes=[])

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        pass  # nothing to revoke - the static token is always valid
