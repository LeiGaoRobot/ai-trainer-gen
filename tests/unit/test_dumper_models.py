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
