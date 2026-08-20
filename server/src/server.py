# -*- coding: utf-8 -*-
"""
Agora Agent & Token Service

HTTP APIs:
- GET  /get_config     -> Agent.generate_config()
- POST /startAgent     -> Agent.start()
- POST /stopAgent      -> Agent.stop()
"""
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from dotenv import load_dotenv

# Load environment variables from .env.local or .env
_base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_base_dir, '.env.local'), override=False)
load_dotenv(os.path.join(_base_dir, '.env'), override=False)

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agora_agent.agentkit.token import generate_convo_ai_token
from agent import Agent
from acp_runtime.codex import CodexAcpClient
from acp_runtime.launch import apply_workspace_override
from acp_runtime.picker import MacOSDirectoryPicker
from acp_runtime.readiness import LocalRuntimeCoordinator
from acp_runtime.routes import build_runtime_router, build_workspace_router
from acp_runtime.workspace import WorkspaceConfigStore, WorkspaceService
from architecture_validation.admin import build_admin_router
from architecture_validation.runtime import state_store
from task_runtime.permissions import PermissionBroker
from task_runtime.runtime import TaskRuntime, TaskRuntimeWorkspaceSwitchGuard
from task_runtime.store import WorkStore
from managed_ingress.capabilities import CapabilityRateLimiter, CapabilityRegistry
from managed_ingress.delivery import WorkDeliveryCoordinator
from managed_ingress.http_policy import IngressHostPolicy
from managed_ingress.ngrok import NgrokCliTunnel
from managed_ingress.public_server import create_public_app as create_managed_public_app
from managed_ingress.runtime import (
    IngressHandlerTracker,
    ManagedIngressCoordinator,
    UvicornListener,
)
from managed_ingress.tools import ManagedWorkTools

logger = logging.getLogger("uvicorn.error")


def _log_route_error(route: str, exc: Exception, **context) -> None:
    """Log route failures with safe request context and a traceback."""
    safe_context = {key: value for key, value in context.items() if value is not None}
    logger.exception(
        "Request failed route=%s context=%s error_type=%s error=%s",
        route,
        safe_context,
        type(exc).__name__,
        exc,
    )


def _to_http_error(exc: Exception) -> HTTPException:
    """Convert SDK exceptions to HTTP errors"""
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=500, detail=f"Internal error: {exc}")

try:
    agent = Agent()
except ValueError as e:
    logger.exception(
        "Failed to initialize Agora Agent SDK. Service will fail if endpoints are called without proper configuration: %s",
        e,
    )
    agent = None


# Local ACP readiness has its own lifecycle and does not start an Agora session.
workspace_service = WorkspaceService(WorkspaceConfigStore.default())
try:
    apply_workspace_override(workspace_service, os.environ)
except ValueError as exc:
    # A bad VOICE_ACP_WORKSPACE must not crash import; surface a clear warning
    # and leave the workspace unconfigured.
    logger.warning("Ignoring VOICE_ACP_WORKSPACE override: %s", exc)
acp_client = CodexAcpClient()
local_runtime = LocalRuntimeCoordinator(workspace_service, acp_client)


router = APIRouter()


def _request_agent(request: Request):
    """Resolve the app-local production Agent or replaceable baseline Agent."""
    return getattr(request.app.state, "agent", agent)


# Request models
class StartAgentRequest(BaseModel):
    """Request body for POST /startAgent"""
    channelName: str
    rtcUid: int
    userUid: int
    parameters: Optional[Dict[str, Any]] = None


class StopAgentRequest(BaseModel):
    """Request body for POST /stopAgent"""
    agentId: str


# API endpoints
def _generate_channel_name() -> str:
    return f"ai-conversation-{int(time.time())}-{random.randint(1000, 9999)}"


@router.get("/get_config")
async def get_config(
    request: Request,
    channel: Optional[str] = Query(default=None),
    uid: Optional[int] = Query(default=None),
):
    """Generate connection configuration"""
    resolved_agent = _request_agent(request)
    if resolved_agent is None:
        raise HTTPException(
            status_code=500,
            detail="Service not properly configured. Please check environment variables.",
        )

    try:
        # Agora RTC accepts uid=0 as "auto assign", but RTM token subjects cannot
        # use 0. Replace missing, zero, or negative values with a generated UID.
        user_uid = random.randint(1000, 9999999) if uid is None or uid <= 0 else uid
        agent_uid = str(random.randint(10000000, 99999999))
        channel_name = channel or _generate_channel_name()

        # Get credentials from environment
        app_id = os.getenv("AGORA_APP_ID")
        app_certificate = os.getenv("AGORA_APP_CERTIFICATE")

        # Generate a one-hour RTC+RTM token and renew it client-side as needed.
        token = generate_convo_ai_token(
            app_id=app_id,
            app_certificate=app_certificate,
            channel_name=channel_name,
            uid=user_uid,
            token_expire=3600,
        )

        config_data = {
            "app_id": app_id,
            "token": token,
            "uid": str(user_uid),
            "channel_name": channel_name,
            "agent_uid": agent_uid,
        }

        return {
            "code": 0,
            "data": config_data,
            "msg": "success",
        }
    except Exception as e:
        _log_route_error("/get_config", e, channel=channel, uid=uid)
        raise _to_http_error(e)


@router.post("/startAgent")
async def start_agent(payload: StartAgentRequest, request: Request):
    """Start agent in a channel"""
    resolved_agent = _request_agent(request)
    if resolved_agent is None:
        raise HTTPException(
            status_code=500,
            detail="Service not properly configured. Please check environment variables.",
        )

    try:
        output_audio_codec = None
        if payload.parameters:
            output_audio_codec = payload.parameters.get("output_audio_codec")

        result = await resolved_agent.start(
            channel_name=payload.channelName,
            agent_uid=payload.rtcUid,
            user_uid=payload.userUid,
            output_audio_codec=output_audio_codec,
        )
        return {"code": 0, "msg": "success", "data": result}
    except Exception as e:
        _log_route_error(
            "/startAgent",
            e,
            channelName=payload.channelName,
            rtcUid=payload.rtcUid,
            userUid=payload.userUid,
        )
        raise _to_http_error(e)


@router.post("/stopAgent")
async def stop_agent(payload: StopAgentRequest, request: Request):
    """Stop agent by ID"""
    resolved_agent = _request_agent(request)
    if resolved_agent is None:
        raise HTTPException(
            status_code=500,
            detail="Service not properly configured. Please check environment variables.",
        )

    try:
        await resolved_agent.stop(payload.agentId)
        return {"code": 0, "msg": "success"}
    except Exception as e:
        _log_route_error("/stopAgent", e, agentId=payload.agentId)
        raise _to_http_error(e)


def local_routes_enabled(env=os.environ) -> bool:
    """Whether to mount the loopback-only derivative routes.

    Ordinary and public deployments expose only the three stable quickstart
    routes. The derivative ``/local/*`` and ``/validation/admin/*`` surfaces
    mount only under the same ``VOICE_ACP_LOCAL_RUNTIME`` opt-in the web
    rewrites use, so ``AGENT_BACKEND_URL`` alone never exposes them.
    """
    return env.get("VOICE_ACP_LOCAL_RUNTIME") == "1"


def create_app(
    *, enable_local_routes: bool, enable_managed_ingress: bool | None = None
) -> FastAPI:
    """Compose the FastAPI app; loopback routes mount only when opted in."""
    work_store = WorkStore.default() if enable_local_routes else None
    permission_broker = (
        PermissionBroker(work_store) if work_store is not None else None
    )
    task_runtime = (
        TaskRuntime(
            workspace_service,
            local_runtime,
            acp_client,
            work_store,
            permission_broker,
        )
        if work_store is not None and permission_broker is not None
        else None
    )
    switch_guard = (
        TaskRuntimeWorkspaceSwitchGuard(work_store, permission_broker)
        if work_store is not None and permission_broker is not None
        else None
    )
    managed_enabled = (
        enable_local_routes
        if enable_managed_ingress is None
        else enable_local_routes and enable_managed_ingress
    )
    managed_ingress = None
    managed_agent = None
    work_delivery = None
    if managed_enabled and task_runtime is not None and work_store is not None:
        managed_registry = CapabilityRegistry()
        managed_host_policy = IngressHostPolicy()
        managed_handler_tracker = IngressHandlerTracker()
        public_app_holder = {}
        managed_ingress = ManagedIngressCoordinator(
            readiness=local_runtime,
            listener_factory=lambda: UvicornListener(public_app_holder["app"]),
            tunnel=NgrokCliTunnel(),
            registry=managed_registry,
            host_policy=managed_host_policy,
            handler_tracker=managed_handler_tracker,
        )
        managed_rate_limiter = CapabilityRateLimiter()
        managed_tools = ManagedWorkTools(
            runtime=task_runtime,
            store=work_store,
            workspace_generation=managed_ingress,
        )
        public_app_holder["app"] = create_managed_public_app(
            tools=managed_tools,
            registry=managed_registry,
            host_policy=managed_host_policy,
            handler_tracker=managed_handler_tracker,
            rate_limiter=managed_rate_limiter,
        )
        try:
            managed_agent = Agent(work_bridge=managed_ingress)
        except ValueError as exc:
            logger.warning(
                "Managed Work Agent is unavailable error_type=%s",
                type(exc).__name__,
            )
        if managed_agent is not None:
            work_delivery = WorkDeliveryCoordinator(
                store=work_store,
                sessions=managed_agent,
                workspace=managed_ingress,
            )
            task_runtime.set_terminal_callback(work_delivery.notify)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        """Recover local Work without starting ACP; close owners inside-out."""
        if work_delivery is not None:
            await work_delivery.start()
        if task_runtime is not None:
            await task_runtime.start()
        if managed_ingress is not None:
            await managed_ingress.start()
        try:
            yield
        finally:
            try:
                if managed_ingress is not None:
                    await managed_ingress.quiesce()
            finally:
                try:
                    if work_delivery is not None:
                        await work_delivery.close()
                finally:
                    try:
                        if managed_agent is not None:
                            await managed_agent.close()
                    finally:
                        try:
                            if managed_ingress is not None:
                                await managed_ingress.close()
                        finally:
                            try:
                                if task_runtime is not None:
                                    await task_runtime.close()
                            finally:
                                try:
                                    await local_runtime.close()
                                finally:
                                    if work_store is not None:
                                        work_store.close()

    application = FastAPI(
        title="Agora Agent & Token Service",
        version="2.0.0",
        description="Agora Conversational AI service",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    if enable_local_routes:
        application.include_router(
            build_workspace_router(
                service=workspace_service,
                picker=MacOSDirectoryPicker(),
                runtime=local_runtime,
                switch_guard=switch_guard,
            )
        )
        application.include_router(build_runtime_router(runtime=local_runtime))
        application.include_router(build_admin_router(store=state_store))
    application.state.task_runtime = task_runtime
    application.state.work_store = work_store
    application.state.managed_ingress = managed_ingress
    application.state.work_delivery = work_delivery
    if managed_enabled:
        application.state.agent = managed_agent
    return application


app = create_app(
    enable_local_routes=local_routes_enabled(),
    enable_managed_ingress=local_routes_enabled(),
)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=port)
