from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.core.config import settings
from app.modules.auth.router import router as auth_router
from app.modules.known_words.router import router as known_words_router


app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    # Only in debug (dev) mode - also allow the frontend dev server when
    # reached over the LAN (e.g. `npm run dev -- --host 0.0.0.0`, opened
    # from a phone as http://<lan-ip>:5173), matching api.ts's own
    # same-host-any-port-8000 origin derivation. Any IPv4:5173 is fine to
    # allow here since this only ever applies when settings.debug is set,
    # never in production.
    allow_origin_regex=r"http://(\d{1,3}\.){3}\d{1,3}:5173" if settings.debug else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(known_words_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=settings.app_name,
        version="0.1.0",
        routes=app.routes,
    )
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
        }
    }
    for path in schema["paths"].values():
        for operation in path.values():
            operation["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi