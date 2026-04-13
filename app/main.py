from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config_store import AuthStore, ConfigStore
from .models import (
    ConfigResponse,
    ConfigUpdate,
    HealthResponse,
    JobType,
    LogResponse,
    LoginRequest,
    LoginResponse,
    TriggerResponse,
    ValidationResult,
)
from .services.job_runner import ConcurrentRunError, JobService
from .services.scheduler_service import SchedulerService
from .storage import RunStore

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("APP_DATA_DIR", str(BASE_DIR / "data"))).resolve()
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR.mkdir(parents=True, exist_ok=True)

config_store = ConfigStore(DATA_DIR / "config.json")
auth_store = AuthStore(DATA_DIR / "auth.json")
run_store = RunStore(DATA_DIR / "runs.json")
job_service = JobService(config_store=config_store, run_store=run_store, data_dir=DATA_DIR)
scheduler_service = SchedulerService(config_store=config_store, job_service=job_service)


@asynccontextmanager
async def lifespan(_: FastAPI):
    config_store.load()
    auth_store.load()
    job_service.cleanup_old_runs()
    job_service.cleanup_old_logs()
    scheduler_service.start()
    try:
        yield
    finally:
        scheduler_service.stop()


app = FastAPI(title="Scheduler Web Console", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=auth_store.load()["session_secret"],
    same_site="lax",
    https_only=False,
)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")


def get_static_version() -> str:
    mtimes = []
    for filename in ("styles.css", "app.js", "login.js"):
        path = STATIC_DIR / filename
        if path.exists():
            mtimes.append(int(path.stat().st_mtime))
    return str(max(mtimes)) if mtimes else "0"


def require_auth(request: Request) -> None:
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    if request.session.get("authenticated"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"static_version": get_static_version()})


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request) -> LoginResponse:
    if not auth_store.verify(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    request.session["authenticated"] = True
    request.session["username"] = payload.username
    return LoginResponse(ok=True, message="登录成功")


@app.post("/auth/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "index.html", {"static_version": get_static_version()})


@app.get("/api/health", response_model=HealthResponse)
def health(_: None = Depends(require_auth)) -> HealthResponse:
    latest = next(iter(run_store.list_runs()), None)
    return HealthResponse(ok=True, scheduler=scheduler_service.status(), latest_run=latest)


@app.get("/api/config", response_model=ConfigResponse)
def get_config(_: None = Depends(require_auth)) -> ConfigResponse:
    return config_store.to_response(config_store.load())


@app.put("/api/config", response_model=ConfigResponse)
def update_config(payload: ConfigUpdate, _: None = Depends(require_auth)) -> ConfigResponse:
    updated = config_store.update(payload)
    scheduler_service.reload()
    return config_store.to_response(updated)


@app.post("/api/config/validate", response_model=ValidationResult)
def validate_config(_: None = Depends(require_auth)) -> ValidationResult:
    try:
        job_service.validate_config()
    except Exception as exc:
        return ValidationResult(ok=False, message=str(exc))
    return ValidationResult(ok=True, message="配置验证成功，登录接口可用。")


@app.post("/api/jobs/{job_type}", response_model=TriggerResponse)
def trigger_job(job_type: JobType, _: None = Depends(require_auth)) -> TriggerResponse:
    try:
        run = job_service.run_job(job_type=job_type, trigger="manual")
    except ConcurrentRunError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TriggerResponse(run_id=run.run_id, status=run.status, started_at=run.started_at)


@app.get("/api/runs")
def list_runs(_: None = Depends(require_auth)) -> list[dict]:
    return [run.model_dump(mode="json") for run in run_store.list_runs()]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, _: None = Depends(require_auth)) -> dict:
    run = run_store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run.model_dump(mode="json")


@app.get("/api/logs", response_model=LogResponse)
def get_logs(run_id: str | None = None, lines: int | None = None, _: None = Depends(require_auth)) -> LogResponse:
    config = config_store.load()
    max_lines = lines or config.log_page_size
    if run_id:
        run = run_store.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        path = Path(run.log_file)
    else:
        runs = run_store.list_runs()
        if not runs:
            return LogResponse(path="", lines=[])
        path = Path(runs[0].log_file)
    if not path.exists():
        return LogResponse(path=str(path), lines=[])
    content = path.read_text(encoding="utf-8").splitlines()
    return LogResponse(path=str(path), lines=content[-max_lines:])
