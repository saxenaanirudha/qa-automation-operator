import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.database.database import init_db
from src.api.routes import health, builds, analysis, analyze


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for database initialization on startup."""
    init_db()
    yield


app = FastAPI(
    title="QA Automation Operator API",
    description="Production-ready REST API service for QA test execution analysis, Quality Gates, multi-build trends, and risk scoring.",
    version="1.0.0",
    lifespan=lifespan,
)

# Ensure reports directory exists and serve static HTML reports
os.makedirs("reports", exist_ok=True)
app.mount("/reports", StaticFiles(directory="reports"), name="reports")


@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirect root endpoint to interactive Swagger API documentation."""
    return RedirectResponse(url="/docs")


# Include routers
app.include_router(health.router)
app.include_router(builds.router)
app.include_router(analysis.router)
app.include_router(analyze.router)
