import os
import shutil
import subprocess

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Service Controller", version="1.5.0")


def csv_env(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


GRAFANA_CONTAINER_NAME = os.getenv("GRAFANA_CONTAINER_NAME", "grafana")
AI_AGENT_CONTAINER_NAME = os.getenv("AI_AGENT_CONTAINER_NAME", "owgw-ai-agent")
MONITORING_PROFILE = os.getenv("MONITORING_COMPOSE_PROFILE", "monitoring")
MONITORING_SERVICES = csv_env(
    "MONITORING_SERVICES",
    "prometheus,grafana,cadvisor,node-exporter,postgres-exporter,kafka-exporter,otel-collector",
)
AI_AGENT_PROFILE = os.getenv("AI_AGENT_COMPOSE_PROFILE", "ai-agent")
AI_AGENT_SERVICES = csv_env("AI_AGENT_SERVICES", "mcp-server,mcp-client")
AI_AGENT_CONTAINERS = csv_env("AI_AGENT_CONTAINERS", f"{AI_AGENT_CONTAINER_NAME},owgw-mcp-server")
COMPOSE_FILE = os.getenv("COMPOSE_FILE", "/opt/deploy/docker-compose.yml")
COMPOSE_PROJECT_MOUNT = os.getenv("COMPOSE_PROJECT_MOUNT", "/opt/deploy")


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


def compose_cmd(compose_file: str, *args: str) -> list[str]:
    return docker_compose_base() + ["-f", compose_file] + list(args)


def resolve_host_compose_file(compose_file: str) -> str:
    mount_path = COMPOSE_PROJECT_MOUNT.rstrip("/")
    if not mount_path:
        return compose_file

    mount_prefix = f"{mount_path}/"
    if not compose_file.startswith(mount_prefix):
        return compose_file

    self_ref = os.getenv("HOSTNAME")
    if not self_ref:
        return compose_file

    template = f'{{{{range .Mounts}}}}{{{{if eq .Destination "{mount_path}"}}}}{{{{.Source}}}}{{{{end}}}}{{{{end}}}}'
    inspect_result = run(docker_cmd("inspect", "-f", template, self_ref), check=False)
    if inspect_result.returncode != 0:
        return compose_file

    host_mount_source = inspect_result.stdout.strip()
    if not host_mount_source:
        return compose_file

    resolved_compose_file = host_mount_source.rstrip("/") + compose_file[len(mount_path):]

    # docker-compose must be able to read the file path locally in this container.
    # Mirror the discovered host path to the mounted project dir via a symlink.
    try:
        if not os.path.exists(host_mount_source):
            os.makedirs(os.path.dirname(host_mount_source), exist_ok=True)
            os.symlink(mount_path, host_mount_source)
    except OSError:
        # Fall back to the original path if symlink creation is not possible.
        return compose_file

    return resolved_compose_file


def run_compose(compose_file: str, *args: str, check: bool = True):
    host_compose_file = resolve_host_compose_file(compose_file)
    compose_dir = os.path.dirname(host_compose_file) or None
    if compose_dir and not os.path.isdir(compose_dir):
        compose_dir = None
    return run(compose_cmd(host_compose_file, *args), cwd=compose_dir, check=check)


def inspect_container(container_name: str) -> dict:
    result = run(docker_cmd("inspect", "-f", "{{.State.Running}}", container_name), check=False)
    if result.returncode != 0:
        stderr = ((result.stderr or "") + " " + (result.stdout or "")).lower()
        if "no such container" in stderr or "no such object" in stderr:
            return {"container": container_name, "exists": False, "running": False}
        raise HTTPException(status_code=500, detail=(result.stderr or result.stdout or "failed to inspect container").strip())
    return {"container": container_name, "exists": True, "running": result.stdout.strip().lower() == "true"}


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
            run_compose(COMPOSE_FILE, "--profile", MONITORING_PROFILE, "up", "-d", *MONITORING_SERVICES, check=True)
            action = "started_via_compose"
        else:
            run_compose(COMPOSE_FILE, "--profile", MONITORING_PROFILE, "stop", *MONITORING_SERVICES, check=True)
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


def ai_agent_status() -> dict:
    services = {}
    running_count = 0
    existing_count = 0

    for container in AI_AGENT_CONTAINERS:
        state = inspect_container(container)
        services[container] = state
        if state["exists"]:
            existing_count += 1
        if state["running"]:
            running_count += 1

    primary = services.get(AI_AGENT_CONTAINER_NAME)
    if primary is None:
        primary = inspect_container(AI_AGENT_CONTAINER_NAME)

    return {
        "container": AI_AGENT_CONTAINER_NAME,
        "exists": bool(primary["exists"]),
        "running": bool(primary["running"]),
        "services": services,
        "existing_count": existing_count,
        "running_count": running_count,
        "total_count": len(AI_AGENT_CONTAINERS),
    }


@app.get("/healthz")
def healthz():
    monitoring = monitoring_status()
    ai_status = ai_agent_status()

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
    if not AI_AGENT_SERVICES:
        raise HTTPException(status_code=500, detail="no ai-agent services configured")

    try:
        if payload.enabled:
            run_compose(COMPOSE_FILE, "--profile", AI_AGENT_PROFILE, "up", "-d", *AI_AGENT_SERVICES, check=True)
            action = "started_via_compose"
        else:
            run_compose(COMPOSE_FILE, "--profile", AI_AGENT_PROFILE, "stop", *AI_AGENT_SERVICES, check=True)
            action = "stopped_via_compose"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip() or (exc.stdout or "").strip() or "ai-agent control command failed"
        raise HTTPException(status_code=500, detail=detail) from exc

    status = ai_agent_status()
    return {
        "ok": True,
        "enabled": payload.enabled,
        "action": action,
        "service": "ai-agent",
        "compose_file": COMPOSE_FILE,
        "profile": AI_AGENT_PROFILE,
        "configured_services": AI_AGENT_SERVICES,
        "container": status["container"],
        "exists": status["exists"],
        "running": status["running"],
        "running_count": status["running_count"],
        "existing_count": status["existing_count"],
        "total_count": status["total_count"],
        "services": status["services"],
    }
