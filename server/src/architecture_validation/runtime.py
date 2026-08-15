"""Process-local validation state shared by loopback and public ASGI apps."""

from .state import CapabilityRegistry, ValidationStateStore


capability_registry = CapabilityRegistry()
state_store = ValidationStateStore()
