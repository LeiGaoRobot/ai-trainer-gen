"""Data models for the dumper module — the canonical StructureJSON format."""

from dataclasses import dataclass, field
import json

__all__ = ["FieldInfo", "ClassInfo", "StructureJSON"]

# Maximum number of classes included in a single LLM prompt
_DEFAULT_MAX_CLASSES = 60


@dataclass
class FieldInfo:
    name:      str
    type:      str     # "float" | "int32" | "bool" | "string" | "Vector3" | ...
    offset:    str     # hex string e.g. "0x58", or "" if unknown
    is_static: bool = False

    def to_dict(self) -> dict:
        d = {"name": self.name, "type": self.type, "offset": self.offset}
        if self.is_static:
            d["static"] = True
        return d


@dataclass
class ClassInfo:
    name:         str
    namespace:    str
    fields:       list[FieldInfo] = field(default_factory=list)
    parent_class: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "namespace": self.namespace}
        if self.parent_class:
            d["parent"] = self.parent_class
        d["fields"] = [f.to_dict() for f in self.fields]
        return d


@dataclass
class StructureJSON:
    """
    Canonical output of any Dumper.
    Passed directly to LLMAnalyzer.analyze().
    """
    engine:        str            # EngineType string value
    version:       str
    classes:       list[ClassInfo] = field(default_factory=list)
    raw_dump_path: str = ""       # path to the original raw dump (for debugging)

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "engine":  self.engine,
            "version": self.version,
            "classes": [c.to_dict() for c in self.classes],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_prompt_str(self, max_classes: int = _DEFAULT_MAX_CLASSES) -> str:
        """
        Produce a compact, token-efficient string for LLM Prompt injection.
        Truncates to max_classes to stay within context limits.

        Format per class::
            [PlayerController (Game.Player)]
            health: float @0x58
            maxHealth: float @0x5C
            gold: int32 @0x64
        """
        lines: list[str] = [
            f"Engine: {self.engine} {self.version}",
            f"Classes ({min(len(self.classes), max_classes)}/{len(self.classes)} shown):",
            "",
        ]
        # Heuristic: prioritise classes whose name looks player/game-relevant
        sorted_classes = _priority_sort(self.classes)
        for cls in sorted_classes[:max_classes]:
            ns = f" ({cls.namespace})" if cls.namespace else ""
            parent = f" : {cls.parent_class}" if cls.parent_class else ""
            lines.append(f"[{cls.name}{ns}{parent}]")
            for f in cls.fields:
                static_tag = " [static]" if f.is_static else ""
                offset_tag = f" @{f.offset}" if f.offset else ""
                lines.append(f"  {f.name}: {f.type}{offset_tag}{static_tag}")
            lines.append("")
        return "\n".join(lines)

    # ── Convenience ───────────────────────────────────────────────────────────

    def find_class(self, name: str) -> ClassInfo | None:
        """Case-insensitive class lookup by name."""
        name_lower = name.lower()
        for cls in self.classes:
            if cls.name.lower() == name_lower:
                return cls
        return None

    def find_field(self, class_name: str, field_name: str) -> FieldInfo | None:
        cls = self.find_class(class_name)
        if cls is None:
            return None
        field_lower = field_name.lower()
        for f in cls.fields:
            if f.name.lower() == field_lower:
                return f
        return None


# ── Sorting heuristic ─────────────────────────────────────────────────────────

_HIGH_PRIORITY_KEYWORDS = {
    "player", "character", "hero", "protagonist",
    "health", "hp", "stamina", "mana", "ammo",
    "gold", "money", "currency", "score",
    "inventory", "item", "weapon", "skill",
    "game", "manager", "controller", "singleton",
}


import re as _re
_CAMEL_RE = _re.compile(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|[a-z]+")


def _camel_tokens(name):
    return [t.lower() for t in _CAMEL_RE.findall(name)]


def _priority_sort(classes):
    """Push classes with gameplay-relevant names to the front.
    Uses CamelCase token matching to avoid substring false-positives.
    """
    def score(cls):
        tokens = set(_camel_tokens(cls.name))
        keyword_hits = len(tokens & _HIGH_PRIORITY_KEYWORDS)
        return (-keyword_hits, cls.name)

    return sorted(classes, key=score)
