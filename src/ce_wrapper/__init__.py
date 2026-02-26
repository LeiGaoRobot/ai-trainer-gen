"""
ce_wrapper — Cheat Engine integration layer.

Public API
──────────
CEProcess         — attached process descriptor
InjectionResult   — result of a script injection attempt
CTBuilder         — serialises GeneratedScript → .ct XML
Sandbox           — AOB pattern validation + hit-count checks
SandboxResult     — result of a sandbox check
"""

from src.ce_wrapper.models import CEProcess, InjectionResult
from src.ce_wrapper.ct_builder import CTBuilder
from src.ce_wrapper.sandbox import Sandbox, SandboxResult

__all__ = [
    "CEProcess",
    "InjectionResult",
    "CTBuilder",
    "Sandbox",
    "SandboxResult",
]
