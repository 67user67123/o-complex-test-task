import hmac
import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT, Settings, get_settings
from app.errors import ServiceError
from app.ollama import OllamaClient
from app.retrieval import KnowledgeIndex
from app.schemas import SuggestRequest, SuggestResponse
from app.service import SuggestionService

logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None, *, ollama=None, index=None) -> FastAPI:
    settings = settings or get_settings()
    ollama = ollama or OllamaClient(settings)
    index = index or KnowledgeIndex(settings, ollama)
    service = SuggestionService(settings, ollama, index)
    application = FastAPI(title="Помощник менеджера", version="0.1.0")
    application.state.service = service
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"] if settings.service_api_key else ["localhost", "127.0.0.1", "[::1]", "testserver"],
    )

    @application.middleware("http")
    async def headers_and_body_limit(request: Request, call_next):
        # Check actual streamed bytes as well as Content-Length to bound JSON
        # parsing before Pydantic validation; also covers chunked requests.
        if request.method == "POST":
            total = 0
            parts = []
            async for chunk in request.stream():
                total += len(chunk)
                if total > 160_000:
                    return JSONResponse({"error": {"code": "body_too_large", "message": "Запрос слишком большой. Сократите переписку."}}, status_code=413)
                parts.append(chunk)
            request._body = b"".join(parts)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'self' https://*.amocrm.ru https://*.amocrm.com"
        )
        if request.url.path in {"/suggest", "/health"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    def authorize(request: Request):
        if not settings.service_api_key:
            return
        provided = request.headers.get("authorization", "")
        expected = f"Bearer {settings.service_api_key}"
        if not hmac.compare_digest(provided.encode(), expected.encode()):
            raise ServiceError("unauthorized", "Введите ключ доступа к сервису.", 401)

    @application.exception_handler(ServiceError)
    async def service_error(_request: Request, exc: ServiceError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status_code)

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        return JSONResponse({"error": {
            "code": "invalid_input",
            "message": "Проверьте обращение (до 6000 символов) и историю (до 30 реплик, суммарно до 20000 символов). Авторы: client или manager.",
        }}, status_code=422)

    @application.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception):
        logger.error("Unhandled error type=%s", type(exc).__name__)
        return JSONResponse({"error": {"code": "internal_error", "message": "Не удалось обработать запрос. Проверьте состояние сервиса и повторите попытку."}}, status_code=500)

    @application.get("/health")
    def health():
        model_status = ollama.status()
        index_status = index.status()
        ready = model_status["status"] == "ready" and index_status["status"] == "ready"
        return {
            "status": "ok" if ready else "degraded",
            "model": settings.ollama_model,
            "embedding_model": settings.embedding_model,
            "ollama": model_status,
            "index": index_status,
        }

    @application.get("/examples", dependencies=[Depends(authorize)])
    def examples():
        return json.loads((ROOT / "data" / "examples.json").read_text(encoding="utf-8"))

    @application.post("/suggest", response_model=SuggestResponse, dependencies=[Depends(authorize)])
    def suggest(payload: SuggestRequest):
        return service.suggest(payload)

    @application.get("/", include_in_schema=False)
    def homepage():
        return FileResponse(STATIC / "index.html")

    # check_dir=False lets the CLI and tests import while static assets are being built.
    application.mount("/static", StaticFiles(directory=STATIC, check_dir=False), name="static")
    return application


app = create_app()
