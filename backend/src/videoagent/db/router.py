"""
FastAPI router for multi-tenancy endpoints.

Provides endpoints for managing companies, users, and customer profiles.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session as DBSession

from .connection import get_db
from . import crud
from .schemas import (
    CompanyCreate, CompanyUpdate, CompanyResponse,
    UserCreate, UserUpdate, UserResponse,
    CustomerProfileCreate, CustomerProfileUpdate, CustomerProfileResponse,
    PronunciationCreate, PronunciationUpdate, PronunciationResponse, PronunciationGenerationResponse,
    ClonedVoiceCreate, ClonedVoiceResponse,
    FeedbackCreate, FeedbackResponse,
)
from ..gemini import GeminiClient
import tempfile
import shutil
from pathlib import Path
from google.genai import types
import requests
import os
from fastapi import Form

router = APIRouter(tags=["multi-tenancy"])


# ============================================================================
# Company Endpoints
# ============================================================================

@router.post("/companies", response_model=CompanyResponse)
def create_company(
    request: CompanyCreate,
    db: DBSession = Depends(get_db),
):
    """Create a new company."""
    # Check if company with same name already exists
    existing = crud.get_company_by_name(db, request.name)
    if existing:
        raise HTTPException(status_code=400, detail="Company with this name already exists")
    
    return crud.create_company(
        db,
        name=request.name,
        video_library_path=request.video_library_path,
        is_test=request.is_test,
        settings=request.settings,
    )


@router.get("/companies", response_model=list[CompanyResponse])
def list_companies(
    include_test: bool = True,
    skip: int = 0,
    limit: int = 100,
    db: DBSession = Depends(get_db),
):
    """List all companies."""
    return crud.list_companies(db, include_test=include_test, skip=skip, limit=limit)


@router.get("/companies/{company_id}", response_model=CompanyResponse)
def get_company(
    company_id: str,
    db: DBSession = Depends(get_db),
):
    """Get a company by ID."""
    company = crud.get_company(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.patch("/companies/{company_id}", response_model=CompanyResponse)
def update_company(
    company_id: str,
    request: CompanyUpdate,
    db: DBSession = Depends(get_db),
):
    """Update a company."""
    company = crud.update_company(
        db,
        company_id,
        name=request.name,
        video_library_path=request.video_library_path,
        is_test=request.is_test,
        settings=request.settings,
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.delete("/companies/{company_id}")
def delete_company(
    company_id: str,
    db: DBSession = Depends(get_db),
):
    """Delete a company and all associated data."""
    if not crud.delete_company(db, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    return {"status": "deleted"}


# ============================================================================
# User Endpoints
# ============================================================================

@router.post("/companies/{company_id}/users", response_model=UserResponse)
def create_user(
    company_id: str,
    request: UserCreate,
    db: DBSession = Depends(get_db),
):
    """Create a new user in a company."""
    # Check company exists
    company = crud.get_company(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Check if email already exists
    existing = crud.get_user_by_email(db, request.email)
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")
    
    return crud.create_user(
        db,
        company_id=company_id,
        email=request.email,
        name=request.name,
        role=request.role,
        is_test=request.is_test,
        settings=request.settings,
    )


@router.get("/companies/{company_id}/users", response_model=list[UserResponse])
def list_users(
    company_id: str,
    include_test: bool = True,
    skip: int = 0,
    limit: int = 100,
    db: DBSession = Depends(get_db),
):
    """List all users in a company."""
    return crud.list_users(db, company_id=company_id, include_test=include_test, skip=skip, limit=limit)


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    db: DBSession = Depends(get_db),
):
    """Get a user by ID."""
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    request: UserUpdate,
    db: DBSession = Depends(get_db),
):
    """Update a user."""
    user = crud.update_user(
        db,
        user_id,
        name=request.name,
        email=request.email,
        role=request.role,
        is_test=request.is_test,
        settings=request.settings,
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    db: DBSession = Depends(get_db),
):
    """Delete a user."""
    if not crud.delete_user(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "deleted"}


# ============================================================================
# Customer Profile Endpoints
# ============================================================================

@router.post("/customers", response_model=CustomerProfileResponse)
def create_customer_profile(
    request: CustomerProfileCreate,
    x_company_id: str = Header(..., alias="X-Company-ID"),
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: DBSession = Depends(get_db),
):
    """Create a new customer profile."""
    # Validate company and user exist
    company = crud.get_company(db, x_company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    user = crud.get_user(db, x_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return crud.create_customer_profile(
        db,
        company_id=x_company_id,
        created_by_user_id=x_user_id,
        name=request.name,
        title=request.title,
        customer_company=request.customer_company,
        industry=request.industry,
        profile_data=request.profile_data,
    )


@router.get("/customers", response_model=list[CustomerProfileResponse])
def list_customer_profiles(
    x_company_id: str = Header(..., alias="X-Company-ID"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    skip: int = 0,
    limit: int = 100,
    db: DBSession = Depends(get_db),
):
    """List customer profiles for the current company/user."""
    return crud.list_customer_profiles(
        db,
        company_id=x_company_id,
        created_by_user_id=x_user_id,  # If provided, filter by user
        skip=skip,
        limit=limit,
    )


@router.get("/customers/{customer_id}", response_model=CustomerProfileResponse)
def get_customer_profile(
    customer_id: str,
    db: DBSession = Depends(get_db),
):
    """Get a customer profile by ID."""
    profile = crud.get_customer_profile(db, customer_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Customer profile not found")
    return profile


@router.patch("/customers/{customer_id}", response_model=CustomerProfileResponse)
def update_customer_profile(
    customer_id: str,
    request: CustomerProfileUpdate,
    db: DBSession = Depends(get_db),
):
    """Update a customer profile."""
    profile = crud.update_customer_profile(
        db,
        customer_id,
        name=request.name,
        title=request.title,
        customer_company=request.customer_company,
        industry=request.industry,
        profile_data=request.profile_data,
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Customer profile not found")
    return profile


@router.delete("/customers/{customer_id}")
def delete_customer_profile(
    customer_id: str,
    db: DBSession = Depends(get_db),
):
    """Delete a customer profile."""
    if not crud.delete_customer_profile(db, customer_id):
        raise HTTPException(status_code=404, detail="Customer profile not found")
    return {"status": "deleted"}


# ============================================================================
# Pronunciation Endpoints
# ============================================================================

@router.get("/pronunciations", response_model=list[PronunciationResponse])
def list_pronunciations(
    session_id: str = Query(...),
    x_company_id: str = Header(..., alias="X-Company-ID"),
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: DBSession = Depends(get_db),
):
    """List pronunciations relevant to the current user and session."""
    return crud.list_pronunciations(
        db,
        company_id=x_company_id,
        user_id=x_user_id,
        session_id=session_id,
    )


@router.post("/pronunciations", response_model=PronunciationResponse)
def create_pronunciation(
    request: PronunciationCreate,
    x_company_id: str = Header(..., alias="X-Company-ID"),
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: DBSession = Depends(get_db),
):
    """Create a new pronunciation."""
    try:
        return crud.create_pronunciation(
            db,
            company_id=x_company_id,
            created_by_user_id=x_user_id,
            word=request.word,
            phonetic_spelling=request.phonetic_spelling,
            session_id=request.session_id,
            always_included=request.always_included,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/pronunciations/{pronunciation_id}")
def delete_pronunciation(
    pronunciation_id: str,
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: DBSession = Depends(get_db),
):
    """Delete a pronunciation."""
    if not crud.delete_pronunciation(db, pronunciation_id, x_user_id):
        raise HTTPException(status_code=404, detail="Pronunciation not found or unauthorized")
    return {"status": "deleted"}

    return {"status": "deleted"}


@router.post("/pronunciations/generate", response_model=PronunciationGenerationResponse)
async def generate_pronunciation(
    file: UploadFile = File(...),
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: DBSession = Depends(get_db),
):
    """Generate phonetic spelling from audio recording."""
    try:
        # Read file bytes directly
        content = await file.read()
        
        mime_type = file.content_type or "audio/wav"
        
        # Call Service
        from videoagent.pronunciation_service import generate_phonetic_spelling
        
        client = GeminiClient()
        return generate_phonetic_spelling(client, content, mime_type)
                
    except Exception as e:
        print(f"Error generating pronunciation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Cloned Voice Endpoints
# ============================================================================

@router.post("/voices/clone", response_model=ClonedVoiceResponse)
async def clone_voice(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    files: list[UploadFile] = File(...),
    x_company_id: str = Header(..., alias="X-Company-ID"),
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: DBSession = Depends(get_db),
):
    """Clone a voice using ElevenLabs API and save to user's profile."""
    # Ensure ELEVENLABS_API_KEY is available
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ElevenLabs API key not configured")

    # Read files for ElevenLabs upload
    file_tuples = []
    try:
        for file in files:
            content = await file.read()
            # ElevenLabs expects: ('files', (filename, file_content, content_type))
            file_tuples.append(("files", (file.filename, content, file.content_type)))
        
        # Call ElevenLabs API
        url = "https://api.elevenlabs.io/v1/voices/add"
        headers = {"xi-api-key": api_key}
        data = {
            "name": name,
        }
        if description:
            data["description"] = description
            
        print(f"Sending request to ElevenLabs API: {url}")
        response = requests.post(url, headers=headers, data=data, files=file_tuples)
        
        if not response.ok:
            error_msg = f"ElevenLabs API error: {response.status_code} {response.text}"
            print(error_msg)
            raise HTTPException(status_code=response.status_code, detail=error_msg)
            
        response_data = response.json()
        elevenlabs_voice_id = response_data.get("voice_id")
        
        if not elevenlabs_voice_id:
            raise HTTPException(status_code=500, detail="Failed to retrieve voice_id from ElevenLabs")
            
        # Optional: Grab voice details (like preview URL) if needed by fetching specific voice 
        # But to keep it faster, we just save what we have
            
        return crud.create_cloned_voice(
            db=db,
            company_id=x_company_id,
            created_by_user_id=x_user_id,
            elevenlabs_voice_id=elevenlabs_voice_id,
            name=name,
            description=description,
        )
        
    except Exception as e:
        print(f"Error cloning voice: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        

@router.get("/voices/cloned", response_model=list[ClonedVoiceResponse])
def list_cloned_voices(
    x_company_id: str = Header(..., alias="X-Company-ID"),
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: DBSession = Depends(get_db),
):
    """List cloned voices for the current user and company defaults."""
    return crud.list_cloned_voices(
        db=db,
        company_id=x_company_id,
        user_id=x_user_id,
    )


@router.delete("/voices/cloned/{voice_id}")
def delete_cloned_voice(
    voice_id: str,
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: DBSession = Depends(get_db),
):
    """Delete a cloned voice."""
    
    # Get the voice to potentially delete it from ElevenLabs as well
    voice = crud.get_cloned_voice(db, voice_id)
    if not voice or voice.created_by_user_id != x_user_id:
        raise HTTPException(status_code=404, detail="Voice not found or unauthorized")
        
    elevenlabs_voice_id = voice.elevenlabs_voice_id

    # Delete from local DB
    if not crud.delete_cloned_voice(db, voice_id, x_user_id):
        raise HTTPException(status_code=404, detail="Voice not found or unauthorized to delete")
        
    # Attempt to delete from ElevenLabs (best effort)
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if api_key:
        try:
            requests.delete(
                f"https://api.elevenlabs.io/v1/voices/{elevenlabs_voice_id}",
                headers={"xi-api-key": api_key}
            )
        except Exception as e:
            print(f"Failed to delete voice {elevenlabs_voice_id} from ElevenLabs: {e}")
            
    return {"status": "deleted"}


# ============================================================================
# Feedback Endpoints
# ============================================================================

@router.put("/feedback", response_model=FeedbackResponse)
def upsert_feedback(
    request: FeedbackCreate,
    x_company_id: str = Header(..., alias="X-Company-ID"),
    x_user_id: str = Header(..., alias="X-User-ID"),
    session_id: str = Query(...),
    db: DBSession = Depends(get_db),
):
    """Create or update feedback (one per user per target)."""
    return crud.upsert_feedback(
        db,
        session_id=session_id,
        company_id=x_company_id,
        user_id=x_user_id,
        target_type=request.target_type,
        target_id=request.target_id,
        rating=request.rating,
        comment=request.comment,
    )


@router.get("/feedback", response_model=list[FeedbackResponse])
def list_feedback(
    session_id: str = Query(...),
    target_type: Optional[str] = Query(None),
    target_id: Optional[str] = Query(None),
    db: DBSession = Depends(get_db),
):
    """List feedback for a session."""
    return crud.list_feedback(
        db,
        session_id=session_id,
        target_type=target_type,
        target_id=target_id,
    )


@router.delete("/feedback/{feedback_id}")
def delete_feedback(
    feedback_id: str,
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: DBSession = Depends(get_db),
):
    """Delete feedback."""
    if not crud.delete_feedback(db, feedback_id, x_user_id):
        raise HTTPException(status_code=404, detail="Feedback not found or unauthorized")
    return {"status": "deleted"}
