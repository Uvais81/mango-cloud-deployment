import os
import shutil
import subprocess

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Service Controller", version="1.4.0")

GRAFANA_CONTAINER_NAME = os.getenv("GRAFANA_CONTAINER_NAME", "grafana")
AI_AGENT_CONTAINER_NAME = os.getenv("AI_AGENT_CONTAINER_NAME", "owgw-ai-agent")
MONITORING_PROFILE = os.getenv("MONITORING_COMPOSE_PROFILE", "monitoring")
MONITORING_SERVICES = [
    service.strip()
    for service in os.getenv(
        "MONITORING_SERVICES",
        "prometheus,grafana,cadvisor,node-exporter,postgres-exporter,kafka-exporter,otel-collector",
    ).split(",")
    if service.strip()
]
COMPOSE_FILE = os.getenv("COMPOSE_FILE", "/opt/deploy/docker-compose.yml")


class ControlRequest(BaseModel):
    enabled: bool


def run(cmd: list[str], cwd: str | None = None, check: bool = True):
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def docker_base() -> list[str]:
    if shutil.which("docker"):
        return ["docker"]
    raise HTTPException(status_code=503, detail="docker is not available")


def docker_cmd(*args: str) -> list[str]:
    return docker_base() + list(args)


def docker_compose_base() -> list[str]:
    if shutil.which("docker"):
        compose_result = run(["docker", "compose", "version"], check=False)
        if compose_result.returncode == 0:
            return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise HTTPException(status_code=503, detail="docker compose is not available")


def compose_cmd(*args: str) -> list[str]:
    return docker_compose_base() + ["-f", COMPOSE_FILE] + list(args)


def list_container_names() -> list[str]:
    result = run(docker_cmd("ps", "-a", "--format", "{{.Names}}"), check=False)
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or (result.stdout or "").strip() or "failed to list containers"
        raise HTTPException(status_code=500, detail=detail)
    return [name.strip() for name in (result.stdout or "").splitlines() if name.strip()]


def normalize_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def resolve_ai_agent_container_name() -> str | None:
    names = list_container_names()
    if AI_AGENT_CONTAINER_NAME in names:
        return AI_AGENT_CONTAINER_NAME

    variants = {
        AI_AGENT_CONTAINER_NAME,
        AI_AGENT_CONTAINER_NAME.replace("-", "_"),
        AI_AGENT_CONTAINER_NAME.replace("_", "-"),
    }

    # Prefer default docker-compose naming convention: <project>_<service>_1
    for name in names:
        for variant in variants:
            if name.endswith(f"_{variant}_1"):
                return name

    normalized_target = normalize_name(AI_AGENT_CONTAINER_NAME)
    for name in names:
        normalized_name = normalize_name(name)
        if normalized_name.endswith(normalized_target) or normalized_target in normalized_name:
            return name

    return None


def inspect_container(container_name: str) -> dict:
    result = run(docker_cmd("inspect", "-f", "{{.State.Running}}", container_name), check=False)
    if result.returncode != 0:
        stderr = ((result.stderr or "") + " " + (result.stdout or "")).lower()
        if "no such container" in stderr or "no such object" in stderr:
            return {"container": container_name, "exists": False, "running": False}
        raise HTTPException(status_code=500, detail=(result.stderr or result.stdout or "failed to inspect container").strip())
    return {"container": container_name, "exists": True, "running": result.stdout.strip().lower() == "true"}


def container_running(container_name: str) -> bool:
    status = inspect_container(container_name)
    if not status["exists"]:
        raise HTTPException(status_code=404, detail=f"container not found: {container_name}")
    return bool(status["running"])


def control_container(container_name: str, payload: ControlRequest):
    _ = container_running(container_name)

    try:
        if payload.enabled:
            run(docker_cmd("start", container_name), check=True)
            action = "started_via_docker"
        else:
            run(docker_cmd("stop", container_name), check=True)
            action = "stopped_via_docker"

        return {
            "ok": True,
            "enabled": payload.enabled,
            "action": action,
            "service": container_name,
            "running_count": 1 if container_running(container_name) else 0,
        }
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() or (exc.stdout or "").strip() or f"{container_name} control command failed"
        raise HTTPException(status_code=500, detail=detail) from exc


def monitoring_status() -> dict:
    services = {}
    running_count = 0
    existing_count = 0

    for service in MONITORING_SERVICES:
        state = inspect_container(service)
        services[service] = state
        if state["exists"]:
            existing_count += 1
        if state["running"]:
            running_count += 1

    return {
        "services": services,
        "existing_count": existing_count,
        "running_count": running_count,
        "total_count": len(MONITORING_SERVICES),
    }


def control_monitoring(payload: ControlRequest):
    if not MONITORING_SERVICES:
        raise HTTPException(status_code=500, detail="no monitoring services configured")

    try:
        if payload.enabled:
            run(
                compose_cmd("--profile", MONITORING_PROFILE, "up", "-d", *MONITORING_SERVICES),
                check=True,
            )
            action = "started_via_compose"
        else:
            run(
                compose_cmd("--profile", MONITORING_PROFILE, "stop", *MONITORING_SERVICES),
                check=True,
            )
            action = "stopped_via_compose"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() or (exc.stdout or "").strip() or "monitoring control command failed"
        raise HTTPException(status_code=500, detail=detail) from exc

    status = monitoring_status()
    return {
        "ok": True,
        "enabled": payload.enabled,
        "action": action,
        "service": "monitoring",
        "profile": MONITORING_PROFILE,
        "configured_services": MONITORING_SERVICES,
        "running_count": status["running_count"],
        "existing_count": status["existing_count"],
        "total_count": status["total_count"],
        "services": status["services"],
    }


@app.get("/healthz")
def healthz():
    monitoring = monitoring_status()
    resolved_ai_container = resolve_ai_agent_container_name()
    ai_status = (
        inspect_container(resolved_ai_container)
        if resolved_ai_container
        else {"container": AI_AGENT_CONTAINER_NAME, "exists": False, "running": False}
    )
    if resolved_ai_container and resolved_ai_container != AI_AGENT_CONTAINER_NAME:
        ai_status["requested_container"] = AI_AGENT_CONTAINER_NAME

    return {
        "status": "ok",
        "services": {
            "grafana": inspect_container(GRAFANA_CONTAINER_NAME),
            "ai-agent": ai_status,
            "monitoring": monitoring,
        },
    }


@app.post("/grafana/control")
@app.post("/api/v1/grafana/control")
def control_grafana(payload: ControlRequest):
    return control_monitoring(payload)


@app.post("/monitoring/control")
@app.post("/api/v1/monitoring/control")
def control_monitoring_stack(payload: ControlRequest):
    return control_monitoring(payload)


@app.post("/ai-agent/control")
@app.post("/api/v1/ai-agent/control")
def control_ai_agent(payload: ControlRequest):
    resolved_ai_container = resolve_ai_agent_container_name()
    if not resolved_ai_container:
        raise HTTPException(status_code=404, detail=f"container not found: {AI_AGENT_CONTAINER_NAME}")
    return control_container(resolved_ai_container, payload)
