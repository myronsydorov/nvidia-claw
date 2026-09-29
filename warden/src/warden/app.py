from fastapi import FastAPI

from warden.models import HealthResponse

app = FastAPI(title="Custody Warden")


@app.get("/api/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", sandboxes_live=0)
