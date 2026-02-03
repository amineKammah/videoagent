"""
Pronunciation Service - Logic for generating phonetic spellings.
"""


from google.genai import types
from videoagent.gemini import GeminiClient
from videoagent.db.schemas import PronunciationGenerationResponse


def generate_phonetic_spelling(
    client: GeminiClient,
    audio_data: bytes,
    mime_type: str = "audio/wav",
) -> PronunciationGenerationResponse:
    """
    Generate phonetic spelling from audio bytes using Gemini.

    Args:
        client: The Gemini client instance.
        audio_data: Raw audio data bytes.
        mime_type: MIME type of the audio data.

    Returns:
        The PronunciationGenerationResponse object.
    """
    try:
        # Construct prompt
        prompt = """
        Listen to this audio clip strictly.
        The user is pronouncing a name or a specific word.
        Return the pronunciation in two formats:
        1. phonetic_spelling: The International Phonetic Alphabet (IPA) representation.
        2. english_spelling: An intuitive English-like phonetic spelling (e.g. "Ah-meen Kah-mah").
        """
        
        # Generate content with structured output
        response = client.client.models.generate_content(
            model=client.config.gemini_model,
            contents=[
                types.Part.from_bytes(data=audio_data, mime_type=mime_type),
                prompt
            ],
            config={
                "response_mime_type": "application/json",
                "response_schema": PronunciationGenerationResponse,
            },
        )
        
        if not response.parsed:
            raise ValueError("Gemini returned empty or invalid response")
            
        return response.parsed
        
    except Exception as e:
        print(f"Gemini generation error: {e}")
        import traceback
        traceback.print_exc()
        raise e
