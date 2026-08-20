"""
Agent

High-level API for managing Agora Conversational AI Agents.
"""
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional, Protocol

from agora_agent import Area, AsyncAgora
from agora_agent.agentkit import Agent as AgoraAgent
from agora_agent.agentkit.vendors import DeepgramSTT, MiniMaxTTS, OpenAI
from architecture_validation.config import ValidationConfig
from architecture_validation.models import RuntimeSessionBinding
from architecture_validation.runtime import capability_registry
from managed_ingress.models import VoiceMcpLease

logger = logging.getLogger("uvicorn.error")

ADA_PROMPT = """You are Ada, an agentic developer advocate from Agora. You help developers understand and build with Agora's Conversational AI platform.

Agora is a real-time communications company. The product you represent is the Agora Conversational AI Engine.

If you do not know a specific fact about Agora, say so plainly and suggest checking docs.agora.io. Keep most replies to one or two sentences unless the user explicitly asks for more detail.
"""

VOICE_VALIDATION_PROMPT = """You are a voice interface to a local coding agent validation harness. Speak briefly.

Use start_work exactly once for a complete executable request that requires project files, commands, code changes, or verification. Ask one clarification when the objective is incomplete. Use get_work_status before answering about existing work, cancel_work for an explicit cancellation, and respond_permission only for an explicit allow or reject of the current Pending Permission.

While a Pending Permission exists, never call start_work. An unrelated yes is never permission. Tool state is authoritative; do not invent Work or permission results.
"""

VOICE_SYSTEM_MESSAGES = [
    {"role": "system", "content": VOICE_VALIDATION_PROMPT}
]
VOICE_WORK_PROMPT = """You are a voice interface to one local coding Agent. Speak briefly and keep ordinary conversation responsive.

One Project Folder is already selected. Registered tools are capabilities you can use. If answering or acting depends on the selected Workspace or local environment, call start_work with the user's objective in natural language. Do not ask the user for a command or say you cannot access the Project Folder unless the tool reports that it is unavailable. Ask one question only when the requested outcome cannot be determined from the conversation.

Treat every tool result as authoritative. Use get_work_status before answering about existing Work. Use cancel_work only after an explicit request to cancel Work; barge-in, silence, or a request to stop speaking never cancels Work. Use respond_permission only for an explicit allow or reject of the current Pending Permission. Unrelated agreement is never permission, and while permission is pending do not start new Work.
"""
VOICE_WORK_SYSTEM_MESSAGES = [{"role": "system", "content": VOICE_WORK_PROMPT}]
VALIDATION_TOOL_NAMES = [
    "start_work",
    "get_work_status",
    "cancel_work",
    "respond_permission",
]


class ManagedWorkBridge(Protocol):
    async def prepare_agent(self) -> VoiceMcpLease: ...

    async def activate_agent(self, lease_id: str, agora_agent_id: str) -> object: ...

    async def revoke_agent(self, lease_id: str) -> None: ...


def build_mcp_servers(
    config: ValidationConfig, binding: RuntimeSessionBinding
) -> list[dict[str, Any]]:
    return [
        {
            "name": "acplocal",
            "endpoint": f"{config.public_base_url}/mcp/",
            "transport": "streamable_http",
            "headers": {
                "Authorization": f"Bearer {binding.mcp_bearer}"
            },
            "allowed_tools": VALIDATION_TOOL_NAMES,
            "timeout_ms": 5000,
        }
    ]


def build_evidence_voice_llm(
    config: ValidationConfig, binding: RuntimeSessionBinding
):
    return OpenAI(
        model=config.model,
        temperature=config.temperature,
        top_p=config.top_p,
        max_tokens=config.max_tokens,
        max_history=config.max_history,
        system_messages=VOICE_SYSTEM_MESSAGES,
        mcp_servers=build_mcp_servers(config, binding),
        greeting_message="Voice-to-ACP validation is ready.",
        failure_message="Please wait a moment.",
    )


def build_work_voice_llm(lease: VoiceMcpLease):
    return OpenAI(
        model="gpt-4o-mini",
        system_messages=VOICE_WORK_SYSTEM_MESSAGES,
        mcp_servers=[
            {
                "name": "acplocal",
                "endpoint": lease.endpoint,
                "transport": "streamable_http",
                "headers": {"Authorization": lease.authorization},
                "allowed_tools": VALIDATION_TOOL_NAMES,
                "timeout_ms": 5000,
            }
        ],
        greeting_message="Voice coding is ready.",
        failure_message="Please wait a moment.",
        max_history=15,
        max_tokens=1024,
        temperature=0.7,
        top_p=0.95,
    )


class Agent:
    """
    High-level wrapper for Agora Conversational AI Agent operations.
    
    Uses AgentSession for full lifecycle management (start/stop),
    which handles Token007 authentication automatically.
    """
    
    def __init__(
        self,
        evidence_config: ValidationConfig | None = None,
        work_bridge: ManagedWorkBridge | None = None,
    ):
        if evidence_config is not None and work_bridge is not None:
            raise ValueError("Evidence and production Work modes are mutually exclusive")
        self.app_id = os.getenv("AGORA_APP_ID")
        self.app_certificate = os.getenv("AGORA_APP_CERTIFICATE")
        self.greeting = os.getenv(
            "AGENT_GREETING",
            "Hi there! I'm Ada, your virtual assistant from Agora. How can I help?",
        )
        self.evidence_config = evidence_config
        self.work_bridge = work_bridge

        if not self.app_id or not self.app_certificate:
            raise ValueError("AGORA_APP_ID and AGORA_APP_CERTIFICATE are required")

        self.client = AsyncAgora(
            area=Area.US,
            app_id=self.app_id,
            app_certificate=self.app_certificate,
        )

        # Track active sessions by agent_id
        self._sessions: Dict[str, Any] = {}
        self._bindings: Dict[str, RuntimeSessionBinding] = {}
        self._work_leases: Dict[str, VoiceMcpLease] = {}

    async def start(
        self,
        channel_name: str,
        agent_uid: int,
        user_uid: int,
        output_audio_codec: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start agent with the same default vendor chain as the Next.js quickstart."""
        if not channel_name or not str(channel_name).strip():
            raise ValueError("channel_name is required and cannot be empty")
        if agent_uid <= 0:
            raise ValueError("agent_uid is required and cannot be empty")
        if user_uid <= 0:
            raise ValueError("user_uid is required and cannot be empty")

        binding = None
        work_lease = None
        if self.evidence_config is not None:
            binding = capability_registry.issue_sync(
                session_id=(
                    f"{channel_name}:{agent_uid}:{secrets.token_urlsafe(8)}"
                ),
                scenario_id=os.getenv("VALIDATION_SCENARIO_ID", "manual"),
                ttl_seconds=3600,
            )
            llm = build_evidence_voice_llm(self.evidence_config, binding)
        elif self.work_bridge is not None:
            work_lease = await self.work_bridge.prepare_agent()
            llm = build_work_voice_llm(work_lease)
        else:
            llm = OpenAI(
                model="gpt-4o-mini",
                greeting_message=self.greeting,
                failure_message="Please wait a moment.",
                max_history=15,
                max_tokens=1024,
                temperature=0.7,
                top_p=0.95,
            )
        stt = DeepgramSTT(model="nova-3", language="en")
        tts = MiniMaxTTS(model="speech_2_6_turbo", voice_id="English_captivating_female1")

        # Optional BYOK example: replace the STT block above and set DEEPGRAM_API_KEY.
        # stt = DeepgramSTT(api_key=os.getenv("DEEPGRAM_API_KEY"), model="nova-3", language="en")

        # Optional BYOK example: replace the LLM block above and set OPENAI_API_KEY.
        # llm = OpenAI(
        #     api_key=os.getenv("OPENAI_API_KEY"),
        #     model="gpt-4o-mini",
        #     greeting_message="Hello! I am your AI assistant. How can I help you?",
        #     failure_message="I'm sorry, I'm having trouble processing your request.",
        #     max_history=15,
        #     max_tokens=1024,
        #     temperature=0.7,
        #     top_p=0.95,
        # )

        # Optional BYOK example: replace the TTS block above and set ELEVENLABS_API_KEY.
        # from agora_agent.agentkit.vendors import ElevenLabsTTS
        # tts = ElevenLabsTTS(
        #     key=os.getenv("ELEVENLABS_API_KEY"),
        #     model_id="eleven_flash_v2_5",
        #     voice_id=os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB"),
        # )

        parameters = {
            "audio_scenario": "chorus",  # web client → ultra-low-latency chorus profile
            "data_channel": "rtm",
            "enable_error_message": True,
            "enable_metrics": True,
        }
        if isinstance(output_audio_codec, str) and output_audio_codec.strip():
            parameters["output_audio_codec"] = output_audio_codec.strip()

        agora_agent = AgoraAgent(
            client=self.client,
            instructions=ADA_PROMPT,
            greeting=self.greeting,
            failure_message="Please wait a moment.",
            max_history=50,
            turn_detection={
                "config": {
                    "speech_threshold": 0.5,
                    "start_of_speech": {
                        "mode": "vad",
                        "vad_config": {
                            "interrupt_duration_ms": 160,
                            "prefix_padding_ms": 300,
                        },
                    },
                    "end_of_speech": {
                        "mode": "vad",
                        "vad_config": {
                            "silence_duration_ms": 480,
                        },
                    },
                },
            },
            advanced_features={"enable_rtm": True, "enable_tools": True},
            parameters=parameters,
        )
        
        agora_agent = (
            agora_agent
            .with_stt(stt)
            .with_llm(llm)
            .with_tts(tts)
        )

        logger.info(
            "Starting Agora agent channel=%s agent_uid=%s user_uid=%s",
            channel_name,
            agent_uid,
            user_uid,
        )

        try:
            session = agora_agent.create_async_session(
                channel=channel_name,
                agent_uid=str(agent_uid),
                remote_uids=[str(user_uid)],
                enable_string_uid=False,
                idle_timeout=30,
                expires_in=3600,
            )
            agent_id = await session.start()
        except Exception as exc:
            if binding is not None:
                capability_registry.expire_session_sync(binding.session_id)
            if work_lease is not None and self.work_bridge is not None:
                await self.work_bridge.revoke_agent(work_lease.lease_id)
                logger.error(
                    "Failed to start Work-capable Agora agent channel=%s "
                    "agent_uid=%s user_uid=%s error_type=%s",
                    channel_name,
                    agent_uid,
                    user_uid,
                    type(exc).__name__,
                )
            else:
                logger.exception(
                    "Failed to start Agora agent channel=%s agent_uid=%s user_uid=%s",
                    channel_name,
                    agent_uid,
                    user_uid,
                )
            raise

        if work_lease is not None and self.work_bridge is not None:
            try:
                await self.work_bridge.activate_agent(work_lease.lease_id, agent_id)
            except Exception:
                await self.work_bridge.revoke_agent(work_lease.lease_id)
                await session.stop()
                raise

        # Save session for later stop
        self._sessions[agent_id] = session
        if binding is not None:
            self._bindings[agent_id] = binding
        if work_lease is not None:
            self._work_leases[agent_id] = work_lease

        logger.info(
            "Started Agora agent agent_id=%s channel=%s agent_uid=%s user_uid=%s",
            agent_id,
            channel_name,
            agent_uid,
            user_uid,
        )
        
        return {
            "agent_id": agent_id,
            "channel_name": channel_name,
            "status": "started",
        }

    async def stop(self, agent_id: str) -> None:
        """Stop a running agent. Falls back to the stateless client path."""
        if not agent_id or not str(agent_id).strip():
            raise ValueError("agent_id is required and cannot be empty")

        session = await self._detach_owned_session(agent_id)
        if session:
            try:
                await session.stop()
                logger.info("Stopped Agora agent from active session agent_id=%s", agent_id)
                return
            except Exception:
                # Fall back to the stateless SDK path if the in-memory session is stale.
                logger.warning(
                    "Failed to stop Agora agent from active session; falling back to client.stop_agent agent_id=%s",
                    agent_id,
                    exc_info=True,
                )

        logger.info("Stopping Agora agent through client.stop_agent agent_id=%s", agent_id)
        await self.client.stop_agent(agent_id)

    def has_work_session(self, agent_id: str) -> bool:
        """Whether the exact Agent still owns an active Work-capable session."""
        return agent_id in self._sessions and agent_id in self._work_leases

    async def say_work_result(self, agent_id: str, text: str) -> bool:
        """Submit safe stored Work speech only to its exact active session."""
        session = self._sessions.get(agent_id)
        if session is None or agent_id not in self._work_leases:
            return False
        await session.say(text, priority="APPEND", interruptable=True)
        return True

    async def close(self) -> None:
        """Revoke and stop every locally owned session without unknown-ID fallback."""
        for agent_id in list(self._sessions):
            session = await self._detach_owned_session(agent_id)
            if session is None:
                continue
            try:
                await session.stop()
            except Exception as exc:
                logger.error(
                    "Failed to close locally owned Agora agent agent_id=%s "
                    "error_type=%s",
                    agent_id,
                    type(exc).__name__,
                )

    async def _detach_owned_session(self, agent_id: str) -> Any | None:
        """Remove local ownership and revoke every capability before stopping."""
        session = self._sessions.pop(agent_id, None)
        binding = self._bindings.pop(agent_id, None)
        if binding is not None:
            capability_registry.expire_session_sync(binding.session_id)
        work_lease = self._work_leases.pop(agent_id, None)
        if work_lease is not None and self.work_bridge is not None:
            await self.work_bridge.revoke_agent(work_lease.lease_id)
        return session

    def active_validation_session(
        self,
    ) -> tuple[str, RuntimeSessionBinding, Any] | None:
        """Return the latest active session for the local validation runner."""
        if not self._bindings:
            return None
        agent_id = next(reversed(self._bindings))
        return agent_id, self._bindings[agent_id], self._sessions[agent_id]
