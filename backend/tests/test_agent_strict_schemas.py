from agents.strict_schema import ensure_strict_json_schema

from videoagent.agent.schemas import GenerateVoiceoverV2Payload


def test_generate_voiceover_v2_payload_is_strict_schema_compatible() -> None:
    schema = GenerateVoiceoverV2Payload.model_json_schema()
    ensure_strict_json_schema(schema)
