from typing import Any
from fastapi import Request
from fastapi.responses import JSONResponse


class MaskgateError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_type: str = "server_error",
        code: str = "internal_error",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.code = code
        self.headers = headers or {}


class AuthenticationError(MaskgateError):
    def __init__(self, message: str = "Invalid or missing API key") -> None:
        super().__init__(
            message=message,
            status_code=401,
            error_type="invalid_request_error",
            code="invalid_api_key",
        )


class BudgetExhaustedError(MaskgateError):
    def __init__(self, message: str = "Monthly budget exceeded") -> None:
        super().__init__(
            message=message,
            status_code=402,
            error_type="insufficient_quota",
            code="budget_exceeded",
        )


class RateLimitError(MaskgateError):
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: int = 60,
    ) -> None:
        super().__init__(
            message=message,
            status_code=429,
            error_type="rate_limit_error",
            code="rate_limit_exceeded",
            headers={"Retry-After": str(retry_after)},
        )


class ModelNotFoundError(MaskgateError):
    def __init__(self, model: str) -> None:
        # Do not leak prompt data; model name is public
        super().__init__(
            message=f"Model '{model}' does not exist or is not configured",
            status_code=404,
            error_type="invalid_request_error",
            code="model_not_found",
        )


class BadRequestError(MaskgateError):
    def __init__(self, message: str = "Invalid request") -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_type="invalid_request_error",
            code="bad_request",
        )


class AllProvidersFailedError(MaskgateError):
    def __init__(self, message: str = "All providers failed to fulfill request") -> None:
        super().__init__(
            message=message,
            status_code=502,
            error_type="bad_gateway",
            code="all_providers_failed",
        )


class RequestTimeoutError(MaskgateError):
    def __init__(self, message: str = "Request timed out") -> None:
        super().__init__(
            message=message,
            status_code=504,
            error_type="timeout_error",
            code="request_timeout",
        )


def format_error_response(
    message: str,
    error_type: str,
    code: str | None = None,
    param: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "message": message,
            "type": error_type,
            "param": param,
            "code": code,
        }
    }


async def maskgate_exception_handler(
    request: Request,
    exc: MaskgateError,
) -> JSONResponse:
    content = format_error_response(
        message=exc.message,
        error_type=exc.error_type,
        code=exc.code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=exc.headers,
    )
