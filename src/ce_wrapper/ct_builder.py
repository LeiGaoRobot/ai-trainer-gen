"""
CTBuilder — serialises a GeneratedScript into a Cheat Engine .ct XML table.

The .ct format is the native Cheat Engine cheat table format.
CE can load it directly via File → Open / the Lua API.

XML structure produced
──────────────────────
<CheatTable>
  <CheatEntries>
    <CheatEntry>
      <Description>feature.name</Description>
      <Hotkey>F1</Hotkey>                    (if set)
      <AssemblerScript>
        [ENABLE]
        ...lua_code or AOB addresses...
        [DISABLE]
      </AssemblerScript>
    </CheatEntry>
  </CheatEntries>
  <LuaScript>full lua_code</LuaScript>
  <AOBSignatures>                            (if aob_sigs present)
    <Signature Name="health_aob">
      <ByteArray>48 8B 05 ?? ?? ?? ??</ByteArray>
      <Offset>0</Offset>
      <Module>game.exe</Module>
    </Signature>
  </AOBSignatures>
</CheatTable>
"""

import logging
import xml.etree.ElementTree as ET
from typing import Optional

from src.analyzer.models import GeneratedScript
from src.resolver.models import EngineContext

__all__ = ["CTBuilder"]

logger = logging.getLogger(__name__)


class CTBuilder:
    """
    Builds a Cheat Engine .ct XML string from a GeneratedScript.

    Usage::

        builder = CTBuilder()
        xml_str = builder.build(script, engine_ctx)
        with open("MyGame.ct", "w", encoding="utf-8") as f:
            f.write(xml_str)
    """

    def build(
        self,
        script: GeneratedScript,
        engine_ctx: Optional[EngineContext] = None,
    ) -> str:
        """
        Serialise *script* into a CE-compatible .ct XML string.

        Args:
            script:     The GeneratedScript produced by LLMAnalyzer.
            engine_ctx: Optional engine context (used for metadata comments).

        Returns:
            A UTF-8 XML string ready to be saved as <name>.ct.
        """
        root = ET.Element("CheatTable")

        # ── Metadata comment ──────────────────────────────────────────────
        engine_note = ""
        if engine_ctx:
            engine_note = f" engine='{engine_ctx.engine_type}'"
        root.set("generated_by", "ai-trainer-gen")
        if engine_note:
            root.set("engine", engine_ctx.engine_type if engine_ctx else "")  # type: ignore[union-attr]

        # ── CheatEntries ──────────────────────────────────────────────────
        entries_el = ET.SubElement(root, "CheatEntries")
        entry_el = ET.SubElement(entries_el, "CheatEntry")

        desc_el = ET.SubElement(entry_el, "Description")
        desc_el.text = script.feature.name

        if script.feature.hotkey:
            hotkey_el = ET.SubElement(entry_el, "Hotkey")
            hotkey_el.text = script.feature.hotkey

        # Embed a minimal assembler-script stub that activates the Lua script
        asm_el = ET.SubElement(entry_el, "AssemblerScript")
        asm_el.text = (
            "[ENABLE]\n"
            f"// Feature: {script.feature.name}\n"
            "// See <LuaScript> section for implementation\n"
            "[DISABLE]\n"
        )

        # ── Full Lua script ───────────────────────────────────────────────
        lua_el = ET.SubElement(root, "LuaScript")
        lua_el.text = script.lua_code

        # ── AOB signatures ────────────────────────────────────────────────
        if script.aob_sigs:
            sigs_el = ET.SubElement(root, "AOBSignatures")
            for sig in script.aob_sigs:
                sig_el = ET.SubElement(sigs_el, "Signature")
                sig_el.set("Name", sig.description or sig.pattern[:20])

                ba_el = ET.SubElement(sig_el, "ByteArray")
                ba_el.text = sig.pattern

                offset_el = ET.SubElement(sig_el, "Offset")
                offset_el.text = str(sig.offset)

                if sig.module:
                    mod_el = ET.SubElement(sig_el, "Module")
                    mod_el.text = sig.module

        return ET.tostring(root, encoding="unicode", xml_declaration=False)
