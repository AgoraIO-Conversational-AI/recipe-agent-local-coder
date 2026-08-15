"""
Agent

High-level API for managing Agora Conversational AI Agents.
"""
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional

from agora_agent import Area, AsyncAgora
from agora_agent.agentkit import Agent as AgoraAgent
from agora_agent.agentkit.vendors import CustomLLM, DeepgramSTT, MiniMaxTTS, OpenAI
from architecture_validation.config import ValidationConfig
from architecture_validation.models import RuntimeSessionBinding
from architecture_validation.runtime import capability_registry

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
VALIDATION_TOOL_NAMES = [
    "start_work",
    "get_work_status",
    "cancel_work",
    "respond_permission",
]


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


def build_voice_llm(
    config: ValidationConfig, binding: RuntimeSessionBinding
):
    shared = {
        "model": config.model,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "max_tokens": config.max_tokens,
        "max_history": config.max_history,
        "system_messages": VOICE_SYSTEM_MESSAGES,
        "mcp_servers": build_mcp_servers(config, binding),
        "greeting_message": "Voice-to-ACP validation is ready.",
        "failure_message": "Please wait a moment.",
    }
    if config.path == "managed":
        return OpenAI(**shared)
    return CustomLLM(
        api_key=binding.llm_callback_bearer,
        base_url=f"{config.public_base_url}/llm/chat/completions",
        **shared,
    )


class Agent:
    """
    High-level wrapper for Agora Conversational AI Agent operations.
    
    Uses AgentSession for full lifecycle management (start/stop),
    which handles Token007 authentication automatically.
    """
    
    def __init__(self):
        self.app_id = os.getenv("AGORA_APP_ID")
        self.app_certificate = os.getenv("AGORA_APP_CERTIFICATE")
        self.greeting = os.getenv(
            "AGENT_GREETING",
            "Hi there! I'm Ada, your virtual assistant from Agora. How can I help?",
        )
        self.validation_config = ValidationConfig.from_env()

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

        binding = capability_registry.issue_sync(
            session_id=(
                f"{channel_name}:{agent_uid}:{secrets.token_urlsafe(8)}"
            ),
            scenario_id=os.getenv("VALIDATION_SCENARIO_ID", "manual"),
            ttl_seconds=3600,
        )
        llm = build_voice_llm(self.validation_config, binding)
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

        session = agora_agent.create_async_session(
            channel=channel_name,
            agent_uid=str(agent_uid),
            remote_uids=[str(user_uid)],
            enable_string_uid=False,
            idle_timeout=30,
            expires_in=3600,
        )

        logger.info(
            "Starting Agora agent channel=%s agent_uid=%s user_uid=%s",
            channel_name,
            agent_uid,
            user_uid,
        )

        try:
            agent_id = await session.start()
        except Exception:
            capability_registry.expire_session_sync(binding.session_id)
            logger.exception(
                "Failed to start Agora agent channel=%s agent_uid=%s user_uid=%s",
                channel_name,
                agent_uid,
                user_uid,
            )
            raise

        # Save session for later stop
        self._sessions[agent_id] = session
        self._bindings[agent_id] = binding

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

        session = self._sessions.pop(agent_id, None)
        binding = self._bindings.pop(agent_id, None)
        if binding is not None:
            capability_registry.expire_session_sync(binding.session_id)
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
