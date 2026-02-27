"""
Unit tests for StructureJSON, ClassInfo, FieldInfo models.
"""

import json
import pytest

from src.dumper.models import ClassInfo, FieldInfo, StructureJSON, _priority_sort


@pytest.fixture
def sample_structure() -> StructureJSON:
    return StructureJSON(
        engine="Unity_IL2CPP",
        version="2022.3.10",
        classes=[
            ClassInfo(
                name="PlayerController",
                namespace="Game.Player",
                parent_class="MonoBehaviour",
                fields=[
                    FieldInfo(name="health",    type="float",  offset="0x58"),
                    FieldInfo(name="maxHealth", type="float",  offset="0x5C"),
                    FieldInfo(name="gold",      type="int32",  offset="0x64"),
                    FieldInfo(name="moveSpeed", type="float",  offset="0x70"),
                    FieldInfo(name="instance",  type="PlayerController",
                              offset="0x10", is_static=True),
                ],
            ),
            ClassInfo(
                name="AudioManager",
                namespace="Game.Audio",
                fields=[
                    FieldInfo(name="volume", type="float", offset="0x20"),
                ],
            ),
        ],
    )


class TestStructureJSONSerialization:
    def test_to_dict_contains_required_keys(self, sample_structure):
        d = sample_structure.to_dict()
        assert d["engine"]  == "Unity_IL2CPP"
        assert d["version"] == "2022.3.10"
        assert len(d["classes"]) == 2

    def test_to_json_valid(self, sample_structure):
        raw = sample_structure.to_json()
        parsed = json.loads(raw)
        assert parsed["engine"] == "Unity_IL2CPP"

    def test_field_offset_preserved(self, sample_structure):
        fields = sample_structure.to_dict()["classes"][0]["fields"]
        health = next(f for f in fields if f["name"] == "health")
        assert health["offset"] == "0x58"

    def test_static_field_flagged(self, sample_structure):
        fields = sample_structure.to_dict()["classes"][0]["fields"]
        instance = next(f for f in fields if f["name"] == "instance")
        assert instance.get("static") is True

    def test_non_static_field_no_static_key(self, sample_structure):
        fields = sample_structure.to_dict()["classes"][0]["fields"]
        health = next(f for f in fields if f["name"] == "health")
        assert "static" not in health


class TestPromptStr:
    def test_prompt_str_contains_class_name(self, sample_structure):
        prompt = sample_structure.to_prompt_str()
        assert "PlayerController" in prompt

    def test_prompt_str_contains_field_with_offset(self, sample_structure):
        prompt = sample_structure.to_prompt_str()
        assert "health" in prompt
        assert "@0x58" in prompt

    def test_prompt_str_contains_engine_header(self, sample_structure):
        prompt = sample_structure.to_prompt_str()
        assert "Unity_IL2CPP" in prompt

    def test_max_classes_truncates(self, sample_structure):
        prompt = sample_structure.to_prompt_str(max_classes=1)
        # Only one class should appear (PlayerController is higher priority)
        assert "AudioManager" not in prompt

    def test_empty_structure(self):
        s = StructureJSON(engine="UE4", version="4.27", classes=[])
        prompt = s.to_prompt_str()
        assert "UE4" in prompt


class TestLookupHelpers:
    def test_find_class_case_insensitive(self, sample_structure):
        cls = sample_structure.find_class("playercontroller")
        assert cls is not None
        assert cls.name == "PlayerController"

    def test_find_class_not_found(self, sample_structure):
        assert sample_structure.find_class("NonExistentClass") is None

    def test_find_field(self, sample_structure):
        field = sample_structure.find_field("PlayerController", "health")
        assert field is not None
        assert field.type == "float"

    def test_find_field_wrong_class(self, sample_structure):
        assert sample_structure.find_field("AudioManager", "health") is None


class TestPrioritySort:
    def test_player_class_sorted_first(self):
        classes = [
            ClassInfo(name="AudioManager",    namespace=""),
            ClassInfo(name="PlayerController", namespace=""),
            ClassInfo(name="UIManager",        namespace=""),
        ]
        sorted_cls = _priority_sort(classes)
        assert sorted_cls[0].name == "PlayerController"

    def test_health_class_sorted_high(self):
        classes = [
            ClassInfo(name="DebugHelper",   namespace=""),
            ClassInfo(name="HealthSystem",  namespace=""),
        ]
        sorted_cls = _priority_sort(classes)
        assert sorted_cls[0].name == "HealthSystem"


class TestIL2CPPDumperParser:
    """Test the .cs file parser without needing the IL2CPPDumper binary."""

    @pytest.fixture
    def parser(self):
        from src.dumper.il2cpp import IL2CPPDumper
        return IL2CPPDumper(dumper_exe="/nonexistent")  # binary not needed for parser tests

    def test_parse_simple_class(self, parser, tmp_path):
        cs = tmp_path / "PlayerController.cs"
        cs.write_text("""\
namespace Game.Player {
    public class PlayerController : MonoBehaviour {
        [FieldOffset(0x58)] public float health;
        [FieldOffset(0x5C)] public float maxHealth;
        [FieldOffset(0x64)] public static int gold;
    }
}
""")
        classes = parser._parse_single_cs(cs)

        assert len(classes) == 1
        cls = classes[0]
        assert cls.name      == "PlayerController"
        assert cls.namespace == "Game.Player"
        assert len(cls.fields) == 3

        health = next(f for f in cls.fields if f.name == "health")
        assert health.type      == "float"
        assert health.offset    == "0x58"
        assert health.is_static is False

        gold = next(f for f in cls.fields if f.name == "gold")
        assert gold.is_static is True

    def test_parse_multiple_classes(self, parser, tmp_path):
        cs = tmp_path / "Multi.cs"
        cs.write_text("""\
namespace Game {
    public class PlayerController {
        [FieldOffset(0x10)] public int hp;
    }
    public class EnemyController {
        [FieldOffset(0x20)] public float damage;
    }
}
""")
        classes = parser._parse_single_cs(cs)
        names = {c.name for c in classes}

        assert "PlayerController" in names
        assert "EnemyController"  in names

    def test_parse_ignores_missing_offset_annotation(self, parser, tmp_path):
        cs = tmp_path / "NoOffset.cs"
        cs.write_text("""\
namespace Test {
    public class Foo {
        public int normalField;
        [FieldOffset(0x10)] public int annotated;
    }
}
""")
        classes = parser._parse_single_cs(cs)
        assert len(classes) == 1
        # Only annotated field should be captured
        assert len(classes[0].fields) == 1
        assert classes[0].fields[0].name == "annotated"

    def test_parse_struct(self, parser, tmp_path):
        cs = tmp_path / "Vec.cs"
        cs.write_text("""\
namespace UnityEngine {
    public struct Vector3 {
        [FieldOffset(0x00)] public float x;
        [FieldOffset(0x04)] public float y;
        [FieldOffset(0x08)] public float z;
    }
}
""")
        classes = parser._parse_single_cs(cs)
        assert len(classes) == 1
        assert classes[0].name == "Vector3"
        assert len(classes[0].fields) == 3


class TestUnityMonoDumperWalkAssemblies:
    """
    Test _MonoReader internals via mocked pymem.
    No Windows or running game required.
    """

    @pytest.fixture
    def reader(self):
        """_MonoReader with a pre-populated _exports dict (no attach needed)."""
        from src.dumper.unity_mono import _MonoReader
        r = _MonoReader("Game.exe", "C:/mono-2.0-bdwgc.dll")
        # Simulate resolved exports
        r._exports = {
            "mono_domain_get": 0x7FF000001000,
        }
        return r

    def test_read_ptr_reads_8_bytes_le(self, reader):
        """_read_ptr reads 8 bytes as a little-endian unsigned int."""
        from unittest.mock import MagicMock
        reader._pm = MagicMock()
        reader._pm.read_bytes.return_value = b"\x01\x00\x00\x00\x00\x00\x00\x00"
        assert reader._read_ptr(0x1000) == 1

    def test_read_int32_reads_4_bytes_le(self, reader):
        """_read_int32 reads 4 bytes as a little-endian unsigned int."""
        from unittest.mock import MagicMock
        reader._pm = MagicMock()
        reader._pm.read_bytes.return_value = b"\x0A\x00\x00\x00"
        assert reader._read_int32(0x1000) == 10

    def test_read_cstring_stops_at_null(self, reader):
        """_read_cstring returns the string up to the first null byte."""
        from unittest.mock import MagicMock
        reader._pm = MagicMock()
        reader._pm.read_bytes.return_value = b"PlayerController\x00garbage"
        result = reader._read_cstring(0x2000)
        assert result == "PlayerController"

    def test_find_root_domain_parses_mov_rax(self, reader):
        """_find_root_domain_ptr finds MOV RAX, [RIP+disp] and follows it."""
        from unittest.mock import MagicMock, patch
        reader._pm = MagicMock()

        # Construct minimal function body: MOV RAX, [RIP+5]; RET
        # Instruction: 48 8B 05 05 00 00 00  (7 bytes, disp=5)
        # RIP at end of instruction = fn_va + 7
        # global_va = (fn_va + 7) + 5 = fn_va + 12
        fn_va = reader._exports["mono_domain_get"]
        code = b"\x48\x8B\x05\x05\x00\x00\x00" + b"\xC3" + b"\x00" * 24
        domain_ptr = 0xDEADBEEF00000001

        def fake_read_bytes(addr, size):
            if addr == fn_va:
                return code
            if addr == fn_va + 12:  # global_va
                return domain_ptr.to_bytes(8, "little")
            return b"\x00" * size

        reader._pm.read_bytes.side_effect = fake_read_bytes
        result = reader._find_root_domain_ptr()
        assert result == domain_ptr

    def test_find_root_domain_raises_if_no_mov_rax(self, reader):
        """_find_root_domain_ptr raises DumperError if pattern not found."""
        from unittest.mock import MagicMock
        from src.exceptions import DumperError
        reader._pm = MagicMock()
        fn_va = reader._exports["mono_domain_get"]
        reader._pm.read_bytes.return_value = b"\x90" * 32  # all NOPs
        with pytest.raises(DumperError, match="mono_domain_get"):
            reader._find_root_domain_ptr()

    def test_walk_assemblies_returns_classes_from_glist(self, reader):
        """_walk_assemblies traverses GList and returns ClassInfo objects."""
        from unittest.mock import MagicMock, patch

        reader._pm = MagicMock()

        # Layout (64-bit addresses):
        DOMAIN   = 0x10000
        GLIST1   = 0x20000
        ASSEMBLY = 0x30000
        IMAGE    = 0x40000

        # Assembly image name string
        IMG_NAME_STR = 0x50000
        # NAMES_ARRAY and NS_ARRAY are arrays of 8-byte char* pointers
        NAMES_ARRAY    = 0x60000
        NS_ARRAY       = 0x61000
        NAME_STR       = 0x62000
        NS_STR_VAL     = 0x63000

        import struct

        def mk_ptr(v: int) -> bytes:
            return struct.pack("<Q", v)

        memory = {
            # domain->domain_assemblies at DOMAIN + 0xD0
            DOMAIN + 0xD0: mk_ptr(GLIST1),
            # GList node 1: data=ASSEMBLY, next=0 (end of list)
            GLIST1 + 0x00: mk_ptr(ASSEMBLY),
            GLIST1 + 0x08: mk_ptr(0),         # next = NULL
            # MonoAssembly->image at ASSEMBLY + 0x60
            ASSEMBLY + 0x60: mk_ptr(IMAGE),
            # MonoImage->assembly_name (char*) at IMAGE + 0x10
            IMAGE + 0x10: mk_ptr(IMG_NAME_STR),
            # MonoImage->n_typedef_rows at IMAGE + 0x18
            IMAGE + 0x18: struct.pack("<I", 1),  # 1 class
            # MonoImage->typedef_names ptr at IMAGE + 0x20 -> points to NAMES_ARRAY
            IMAGE + 0x20: mk_ptr(NAMES_ARRAY),
            # MonoImage->typedef_namespaces ptr at IMAGE + 0x28 -> points to NS_ARRAY
            IMAGE + 0x28: mk_ptr(NS_ARRAY),
            # NAMES_ARRAY[0] -> pointer to the class name string
            NAMES_ARRAY + 0x00: mk_ptr(NAME_STR),
            # NS_ARRAY[0] -> pointer to the namespace string
            NS_ARRAY    + 0x00: mk_ptr(NS_STR_VAL),
            # Actual strings
            IMG_NAME_STR: b"Assembly-CSharp\x00",
            NAME_STR:     b"PlayerController\x00",
            NS_STR_VAL:   b"Game.Player\x00",
        }

        def fake_read(addr, size):
            for base, data in memory.items():
                if addr == base:
                    return data[:size]
            return b"\x00" * size

        reader._pm.read_bytes.side_effect = fake_read

        # Patch _find_root_domain_ptr to return our fake domain
        with patch.object(reader, "_find_root_domain_ptr", return_value=DOMAIN):
            classes = reader._walk_assemblies()

        assert len(classes) >= 1
        names = [c.name for c in classes]
        assert "PlayerController" in names

    def test_walk_assemblies_handles_null_assembly_gracefully(self, reader):
        """NULL assembly pointer in GList is skipped without crashing."""
        from unittest.mock import MagicMock, patch
        import struct

        reader._pm = MagicMock()
        DOMAIN = 0x10000
        GLIST1 = 0x20000

        def mk_ptr(v): return struct.pack("<Q", v)
        memory = {
            DOMAIN + 0xD0: mk_ptr(GLIST1),
            GLIST1 + 0x00: mk_ptr(0),   # NULL assembly
            GLIST1 + 0x08: mk_ptr(0),   # end of list
        }
        reader._pm.read_bytes.side_effect = lambda a, s: memory.get(a, b"\x00"*s)[:s]

        with patch.object(reader, "_find_root_domain_ptr", return_value=DOMAIN):
            classes = reader._walk_assemblies()

        assert classes == []

    def test_walk_assemblies_caps_at_max_assemblies(self, reader):
        """GList longer than _MAX_ASSEMBLIES is capped (infinite loop prevention)."""
        from unittest.mock import MagicMock, patch
        import struct

        reader._pm = MagicMock()
        DOMAIN = 0x10000

        # Build a long GList (each node has NULL assembly, so they're all skipped)
        nodes = list(range(0x20000, 0x20000 + 600 * 0x10, 0x10))  # 600 nodes

        def mk_ptr(v): return struct.pack("<Q", v)

        memory: dict = {DOMAIN + 0xD0: mk_ptr(nodes[0])}
        for i, node in enumerate(nodes):
            memory[node + 0x00] = mk_ptr(0)         # NULL assembly (skip)
            memory[node + 0x08] = mk_ptr(nodes[i+1] if i < len(nodes)-1 else 0)

        reader._pm.read_bytes.side_effect = lambda a, s: memory.get(a, b"\x00"*s)[:s]

        from src.dumper.unity_mono import _MAX_ASSEMBLIES

        with patch.object(reader, "_find_root_domain_ptr", return_value=DOMAIN):
            classes = reader._walk_assemblies()

        assert classes == []
        # Each capped iteration reads assembly_ptr + next_ptr = 2 reads per node
        # Plus the initial glist_ptr read = 1. Total <= _MAX_ASSEMBLIES * 2 + 1
        assert reader._pm.read_bytes.call_count <= _MAX_ASSEMBLIES * 2 + 1
