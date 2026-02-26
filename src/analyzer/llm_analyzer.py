"""
LLMAnalyzer — orchestrates LLM calls to generate CE Lua scripts.

Supported backends (selected via `backend` constructor arg):
  • "anthropic"  — Claude models via anthropic SDK
  • "openai"     — GPT models via openai SDK
  • "stub"       — deterministic no-network stub for unit testing

Retry policy: exponential back-off, configurable max attempts.
Response parsing: extracts [SCRIPT_BEGIN]...[SCRIPT_END] and
  [AOB_BEGIN]...[AOB_END] blocks from the LLM output.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from src.dumper.models import StructureJSON
from src.exceptions import LLMAPIError, ScriptGenerationError

from .models import AOBSignature, GeneratedScript, TrainerFeature
from .prompts.builder import PromptBuilder

__all__ = ["LLMAnalyzer"]

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class LLMConfig:
    """Runtime configuration for LLMAnalyzer."""
    backend:     str   = "anthropic"      # "anthropic" | "openai" | "stub"
    model:       str   = ""               # empty = use backend default
    api_key:     str   = ""               # empty = read from env
    max_tokens:  int   = 4096
    temperature: float = 0.2              # low = more deterministic code
    max_retries: int   = 3
    retry_delay: float = 2.0              # seconds (doubled each attempt)
    timeout:     float = 60.0            # per-request timeout in seconds


_DEFAULT_MODELS = {
    "anthropic": "claude-3-5-sonnet-20241022",
    "openai":    "gpt-4o",
    "stub":      "stub-v1",
}


# ── Response parser ───────────────────────────────────────────────────────────

_SCRIPT_RE = re.compile(r"\[SCRIPT_BEGIN\](.*?)\[SCRIPT_END\]", re.DOTALL)
_AOB_RE    = re.compile(r"\[AOB_BEGIN\](.*?)\[AOB_END\]",    re.DOTALL)
_AOB_LINE_RE = re.compile(
    r"^(?P<pattern>[0-9A-Fa-f ?]+?)\s*\|"   # pattern (may contain spaces)
    r"\s*(?P<offset>-?\d+)\s*\|"             # signed byte offset
    r"\s*(?P<module>[^|]*?)\s*\|"            # module name (may be empty)
    r"\s*(?P<description>.*)$"               # description
)


def _parse_response(
    raw: str,
    feature: TrainerFeature,
    model_id: str,
    prompt_tokens: int = 0,
    output_tokens: int = 0,
) -> GeneratedScript:
    """
    Extract [SCRIPT_BEGIN]...[SCRIPT_END] and [AOB_BEGIN]...[AOB_END] blocks.

    Raises ScriptGenerationError if no script block is found.
    """
    script_m = _SCRIPT_RE.search(raw)
    if not script_m:
        raise ScriptGenerationError(
            "LLM response did not contain [SCRIPT_BEGIN]...[SCRIPT_END] block. "
            f"Raw response (first 200 chars): {raw[:200]!r}"
        )
    lua_code = script_m.group(1).strip()

    aob_sigs: list[AOBSignature] = []
    aob_m = _AOB_RE.search(raw)
    if aob_m:
        for line in aob_m.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = _AOB_LINE_RE.match(line)
            if m:
                aob_sigs.append(AOBSignature(
                    pattern=m.group("pattern").strip(),
                    offset=int(m.group("offset")),
                    module=m.group("module").strip(),
                    description=m.group("description").strip(),
                ))
            else:
                logger.warning("Could not parse AOB line: %r", line)

    return GeneratedScript(
        lua_code=lua_code,
        feature=feature,
        aob_sigs=aob_sigs,
        model_id=model_id,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        raw_response=raw,
    )


# ── Backend adapters ──────────────────────────────────────────────────────────

class _AnthropicBackend:
    def __init__(self, config: LLMConfig) -> None:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from exc
        kwargs: dict = {"max_retries": 0}  # we handle retries ourselves
        if config.api_key:
            kwargs["api_key"] = config.api_key
        self._client = anthropic.Anthropic(**kwargs)
        self._config = config

    def call(self, system: str, user: str, model: str) -> tuple[str, int, int]:
        """Returns (response_text, prompt_tokens, output_tokens)."""
        resp = self._client.messages.create(
            model=model,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = resp.content[0].text
        return text, resp.usage.input_tokens, resp.usage.output_tokens


class _OpenAIBackend:
    def __init__(self, config: LLMConfig) -> None:
        try:
            import openai  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "openai package not installed. Run: pip install openai"
            ) from exc
        kwargs: dict = {}
        if config.api_key:
            kwargs["api_key"] = config.api_key
        self._client = openai.OpenAI(**kwargs)
        self._config = config

    def call(self, system: str, user: str, model: str) -> tuple[str, int, int]:
        resp = self._client.chat.completions.create(
            model=model,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        prompt_t  = usage.prompt_tokens     if usage else 0
        output_t  = usage.completion_tokens if usage else 0
        return text, prompt_t, output_t


class _StubBackend:
    """Deterministic stub — no network, for unit tests."""

    def __init__(self, config: "LLMConfig") -> None:
        pass  # config not used

    _TEMPLATE = """\
[SCRIPT_BEGIN]
-- Feature: {feature_name}
-- Engine: {engine}
-- Generated by stub backend

local cheatEnabled = false

local function applyCheat()
  local baseAddr = AOBScan("{aob_pattern}")
  if baseAddr then
    writeFloat(baseAddr + 0x58, 9999.0)
  end
end

local function toggleCheat()
  cheatEnabled = not cheatEnabled
  if cheatEnabled then
    applyCheat()
  end
end

registerHotkey(0x70, toggleCheat)  -- F1
[SCRIPT_END]
[AOB_BEGIN]
{aob_pattern} | 0 | GameAssembly.dll | stub health pattern
[AOB_END]
"""

    def call(self, system: str, user: str, model: str) -> tuple[str, int, int]:
        # Extract feature name from the user message
        feature_name = "Unknown"
        engine = "Unknown"
        for line in user.splitlines():
            if line.startswith("Name:"):
                feature_name = line.split(":", 1)[1].strip()
            if line.startswith("Engine:"):
                engine = line.split(":", 1)[1].strip()

        aob_pattern = "89 87 ?? ?? 00 00 F3 0F 11 87 ?? ?? 00 00"
        text = self._TEMPLATE.format(
            feature_name=feature_name,
            engine=engine,
            aob_pattern=aob_pattern,
        )
        return text, len(user) // 4, len(text) // 4


_BACKEND_MAP = {
    "anthropic": _AnthropicBackend,
    "openai":    _OpenAIBackend,
    "stub":      _StubBackend,
}


# ── LLMAnalyzer ───────────────────────────────────────────────────────────────

class LLMAnalyzer:
    """
    Analyze a StructureJSON + TrainerFeature and produce a GeneratedScript.

    Parameters
    ----------
    config : LLMConfig (or None → defaults)

    Usage::
        analyzer = LLMAnalyzer(LLMConfig(backend="anthropic"))
        script = analyzer.analyze(structure, feature)
    """

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self._config = config or LLMConfig()
        backend_cls = _BACKEND_MAP.get(self._config.backend)
        if backend_cls is None:
            raise ValueError(
                f"Unknown LLM backend: {self._config.backend!r}. "
                f"Choose from: {list(_BACKEND_MAP)}"
            )
        self._backend = backend_cls(self._config)
        self._builder = PromptBuilder()
        self._model = self._config.model or _DEFAULT_MODELS[self._config.backend]

    def analyze(
        self,
        structure: StructureJSON,
        feature: TrainerFeature,
        engine_context=None,   # Optional[EngineContext] — avoid circular import
        max_classes: int = 60,
    ) -> GeneratedScript:
        """
        Generate a CE Lua script for the given feature.

        Parameters
        ----------
        structure       : dumped game structure (from Dumper module)
        feature         : what to implement (TrainerFeature)
        engine_context  : Optional[EngineContext] — if provided, uses engine-
                          specific resolution strategy instead of generic AOB.
                          Obtain via: resolver.get_resolver(engine_type).resolve(…)
                          then attach to an EngineContext.
        max_classes     : passed to PromptBuilder / StructureJSON.to_prompt_str

        Returns
        -------
        GeneratedScript — validated Lua code + AOB signatures

        Raises
        ------
        LLMAPIError           — network / authentication failure
        ScriptGenerationError — LLM returned unparseable output after all retries
        """
        system, user = self._builder.build(structure, feature, engine_context, max_classes)

        last_exc: Optional[Exception] = None
        delay = self._config.retry_delay

        for attempt in range(1, self._config.max_retries + 1):
            try:
                logger.info(
                    "LLM call attempt %d/%d  model=%s  feature=%s",
                    attempt, self._config.max_retries, self._model, feature.name
                )
                raw, prompt_t, output_t = self._backend.call(system, user, self._model)

                script = _parse_response(
                    raw, feature, self._model, prompt_t, output_t
                )
                logger.info(
                    "Script generated: %d lines, %d AOBs  (tokens: in=%d out=%d)",
                    script.lua_code.count("\n") + 1,
                    len(script.aob_sigs),
                    prompt_t, output_t,
                )
                return script

            except ScriptGenerationError as exc:
                logger.warning("Attempt %d: bad response format: %s", attempt, exc)
                last_exc = exc
            except Exception as exc:
                logger.warning("Attempt %d: API error: %s", attempt, exc)
                last_exc = LLMAPIError(str(exc))

            if attempt < self._config.max_retries:
                logger.debug("Retrying in %.1f s …", delay)
                time.sleep(delay)
                delay *= 2  # exponential back-off

        # All attempts exhausted
        if isinstance(last_exc, LLMAPIError):
            raise last_exc
        raise ScriptGenerationError(
            f"Failed to generate script for '{feature.name}' after "
            f"{self._config.max_retries} attempt(s). Last error: {last_exc}"
        )

    def analyze_batch(
        self,
        structure: StructureJSON,
        features: list[TrainerFeature],
        engine_context=None,   # Optional[EngineContext]
        max_classes: int = 60,
    ) -> list[GeneratedScript]:
        """
        Generate scripts for multiple features sequentially.
        Errors on individual features are logged but do not abort the batch.

        Returns a list of successful GeneratedScript objects.
        """
        results: list[GeneratedScript] = []
        for feat in features:
            try:
                results.append(self.analyze(structure, feat, engine_context, max_classes))
            except (LLMAPIError, ScriptGenerationError) as exc:
                logger.error("Failed to generate script for '%s': %s", feat.name, exc)
        return results
