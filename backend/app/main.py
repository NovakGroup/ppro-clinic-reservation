"""Vstupní bod aplikace: REST API pod /api, webové rozhraní pro recepci na /."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from app.api.routers.clinic import router
from app.domain.errors import DomainError

_HERE = Path(__file__).resolve().parent
# V Docker image leží frontend vedle balíčku app, v repozitáři o úroveň výš.
FRONTEND = next(
    (p for p in (_HERE.parent / "frontend" / "index.html", _HERE.parent.parent / "frontend" / "index.html") if p.exists()),
    _HERE.parent / "frontend" / "index.html",
)

app = FastAPI(
    title="Ordinace Na Vyhlídce – rezervační systém",
    description="REST API pro recepci: pacienti, rezervace, návštěvy, výkony a měsíční výkazy.",
    version="1.0.0",
)
app.include_router(router)


@app.exception_handler(DomainError)
def domain_error_handler(_: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(RequestValidationError)
def request_validation_handler(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(x) for x in first.get("loc", [])[1:])
    return JSONResponse(status_code=422, content={"detail": f"Neplatný vstup ({field}): {first.get('msg', '')}"})


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND)
