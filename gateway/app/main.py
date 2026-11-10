from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.v1 import router as v1_router
from app.core.errors import MaskgateError, format_error_response, maskgate_exception_handler
from app.db.session import close_db, get_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Lifespan startup
    yield
    # Lifespan shutdown
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Maskgate",
        description="A compliance-first LLM gateway",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS locked down / configured
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception Handlers
    app.add_exception_handler(MaskgateError, maskgate_exception_handler)  # type: ignore[arg-type]

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        msg = errors[0]["msg"] if errors else "Invalid request body"
        return JSONResponse(
            status_code=400,
            content=format_error_response(
                message=msg,
                error_type="invalid_request_error",
                code="bad_request",
            ),
        )

    # Include Routers
    app.include_router(health_router)
    app.include_router(v1_router)
    app.include_router(admin_router)

    return app


app = create_app()
