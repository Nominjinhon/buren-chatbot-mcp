"""Single MCP server exposing every read-only loan/analytics/customer tool
for the chatbot agent.

Originally split into three servers (loan data, financial analytics,
customer profile), one process per domain; consolidated into one file per
explicit user request. Every tool still delegates to its respective
app.services module - this file never touches the ORM directly.

DTI is computed entirely in app.services.analytics_service using plain
arithmetic - never by an LLM. This server only fetches and returns the result.
"""

import logging
import os
import time
import uuid

from mcp.server import MCPServer
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import UserMessage
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.database.models import LoanStatus, LoanType
from app.database.session import AsyncSessionLocal
from app.mcp_servers.oauth_provider import SingleTokenOAuthProvider
from app.schemas.analytics import DTIResult
from app.schemas.customer import CustomerProfile
from app.schemas.loan import Loan
from app.schemas.payment import OverduePayment
from app.services import analytics_service, loan_service

_call_logger = logging.getLogger("buren_server.calls")


class _CallLoggingMiddleware:
    """Logs every inbound MCP request - which tool (or other method) ran, and
    how long it took.

    The SDK itself only logs failures, and on the HTTP transport every call
    looks like a generic `POST /mcp` from the outside (the tool name is
    inside the JSON-RPC body, which Railway's HTTP request logs don't
    parse) - this is the only way to see "what tool was called" in
    Railway's Deploy log tab. Works identically over stdio, so it's just as
    useful for local dev.
    """

    async def __call__(self, ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
        label = ctx.method
        if ctx.method == "tools/call" and ctx.params:
            label = f"tools/call {ctx.params.get('name')}(arguments={ctx.params.get('arguments')})"
        started = time.monotonic()
        try:
            result = await call_next(ctx)
        except Exception:
            _call_logger.info("%s -> error (%.0fms)", label, (time.monotonic() - started) * 1000)
            raise
        _call_logger.info("%s -> ok (%.0fms)", label, (time.monotonic() - started) * 1000)
        return result


def _http_auth() -> tuple[OAuthAuthorizationServerProvider | None, AuthSettings | None]:
    """OAuth wiring for the HTTP (Railway) deployment only - the stdio transport
    (the agent, tests) never sets these env vars, so it always gets auth=None
    here and is completely unaffected. `MCPServer` bakes auth in at
    construction time (`streamable_http_app()` can't override it per-call),
    so this has to run before `mcp = MCPServer(...)` below rather than in
    mcp_service/server.py where the rest of the HTTP-only wiring lives.
    """
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    token = os.environ.get("MCP_HTTP_TOKEN")
    if not domain or not token:
        return None, None
    base_url = f"https://{domain}"
    settings = AuthSettings(
        issuer_url=base_url,
        resource_server_url=f"{base_url}/mcp",
        client_registration_options=ClientRegistrationOptions(enabled=True),
        # Silences a deprecation warning on newer mcp SDK versions than the one
        # pinned locally (uv.lock) - the Railway image installs "mcp[cli]"
        # unpinned. Harmlessly ignored as an unknown field on the older local
        # SDK (pydantic's default extra="ignore"). True is correct here
        # regardless of version: our SingleTokenOAuthProvider only ever issues
        # tokens for this one resource, so refusing tokens issued for another
        # resource costs nothing.
        validate_token_resource=True,
    )
    return SingleTokenOAuthProvider(token), settings


_auth_server_provider, _auth_settings = _http_auth()

mcp = MCPServer(
    "buren_server",
    auth_server_provider=_auth_server_provider,
    auth=_auth_settings,
    middleware=[_CallLoggingMiddleware()],
)


@mcp.custom_route("/health", methods=["GET"])
async def _health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ToolError(f"Invalid {field_name}: {value!r} is not a valid UUID.") from exc


@mcp.resource("resource://loan-types")
def loan_types() -> list[str]:
    """Static reference list of valid loan type values."""
    return [loan_type.value for loan_type in LoanType]


@mcp.resource("resource://loan-statuses")
def loan_statuses() -> list[str]:
    """Static reference list of valid loan status values.

    These three are mutually exclusive on the `status` field itself - a loan
    is exactly one of them. `get_active_loans` groups `active` and `overdue`
    together for display (both are still open/owed), but that's a grouping
    at the tool layer, not a change to the underlying status values here.
    """
    return [loan_status.value for loan_status in LoanStatus]


@mcp.tool()
async def get_active_loans(customer_id: str) -> list[Loan]:
    """Return the customer's currently open loans (`active` or `overdue`
    status) - excludes only `closed` loans."""
    async with AsyncSessionLocal() as session:
        return await loan_service.get_active_loans(
            session, _parse_uuid(customer_id, "customer_id")
        )


@mcp.tool()
async def get_loan_by_id(loan_id: str) -> Loan:
    """Return a single loan's full detail by its id."""
    async with AsyncSessionLocal() as session:
        loan = await loan_service.get_loan_by_id(session, _parse_uuid(loan_id, "loan_id"))
    if loan is None:
        raise ToolError(f"No loan found with id {loan_id!r}.")
    return loan


@mcp.tool()
async def get_overdue_payments(customer_id: str) -> list[OverduePayment]:
    """Return the customer's currently-unpaid late payments."""
    async with AsyncSessionLocal() as session:
        return await loan_service.get_overdue_payments(
            session, _parse_uuid(customer_id, "customer_id")
        )


@mcp.prompt()
async def summarize_overdue(customer_id: str) -> UserMessage:
    """Ask the model to summarize an already-fetched list of overdue
    payments in plain language, without inventing or altering any of them."""
    parsed_id = _parse_uuid(customer_id, "customer_id")
    async with AsyncSessionLocal() as session:
        payments = await loan_service.get_overdue_payments(session, parsed_id)

    if not payments:
        return UserMessage("This customer has no overdue payments. Say so plainly.")

    lines = "\n".join(
        f"- {payment.loan_type.value} loan, due {payment.due_date}, "
        f"{payment.days_overdue} days overdue, amount {payment.amount}"
        for payment in payments
    )
    return UserMessage(
        "Using ONLY this already-fetched list of overdue payments - do not "
        "invent or alter any of them - summarize them in plain language:\n"
        f"{lines}"
    )


@mcp.tool()
async def calculate_dti(customer_id: str) -> DTIResult:
    """Compute the customer's debt-to-income ratio from active + overdue loans."""
    parsed_id = _parse_uuid(customer_id, "customer_id")
    async with AsyncSessionLocal() as session:
        result = await analytics_service.calculate_dti(session, parsed_id)
    if result is None:
        raise ToolError(f"No customer found with id {customer_id!r}.")
    return result


@mcp.prompt()
async def explain_dti(customer_id: str) -> UserMessage:
    """Ask the model to narrate an already-computed DTI result in plain
    language, without recomputing or altering any of the numbers."""
    parsed_id = _parse_uuid(customer_id, "customer_id")
    async with AsyncSessionLocal() as session:
        result = await analytics_service.calculate_dti(session, parsed_id)
    if result is None:
        raise ValueError(f"No customer found with id {customer_id!r}.")
    return UserMessage(
        "Using ONLY these already-computed numbers - do not recompute or "
        "alter them - explain this customer's debt-to-income ratio in plain "
        "language:\n"
        f"- Monthly income: {result.monthly_income}\n"
        f"- Total monthly debt payments: {result.total_monthly_debt_payments}\n"
        f"- DTI ratio: {result.dti_ratio}%"
    )


@mcp.tool()
async def get_customer_income(customer_id: str) -> float:
    """Return the customer's monthly income in MNT."""
    parsed_id = _parse_uuid(customer_id, "customer_id")
    async with AsyncSessionLocal() as session:
        income = await analytics_service.get_customer_income(session, parsed_id)
    if income is None:
        raise ToolError(f"No customer found with id {customer_id!r}.")
    return income


@mcp.tool()
async def get_customer_profile(customer_id: str) -> CustomerProfile:
    """Return the customer's profile (name, monthly income, created_at)."""
    parsed_id = _parse_uuid(customer_id, "customer_id")
    async with AsyncSessionLocal() as session:
        profile = await loan_service.get_customer_profile(session, parsed_id)
    if profile is None:
        raise ToolError(f"No customer found with id {customer_id!r}.")
    return profile


if __name__ == "__main__":
    mcp.run(transport="stdio")
