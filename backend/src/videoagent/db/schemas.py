"""
Pydantic schemas for multi-tenancy API endpoints.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Company Schemas
# ============================================================================

class CompanyCreate(BaseModel):
    """Request to create a new company."""
    name: str
    video_library_path: Optional[str] = None
    is_test: bool = True
    settings: Optional[dict] = None


class CompanyUpdate(BaseModel):
    """Request to update a company."""
    name: Optional[str] = None
    video_library_path: Optional[str] = None
    is_test: Optional[bool] = None
    settings: Optional[dict] = None


class CompanyResponse(BaseModel):
    """Company response schema."""
    id: str
    name: str
    video_library_path: Optional[str] = None
    is_test: bool
    settings: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# User Schemas
# ============================================================================

class UserCreate(BaseModel):
    """Request to create a new user."""
    email: str
    name: str
    role: str = "editor"  # admin, editor, viewer
    is_test: bool = True
    settings: Optional[dict] = None


class UserUpdate(BaseModel):
    """Request to update a user."""
    email: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    is_test: Optional[bool] = None
    settings: Optional[dict] = None


class UserResponse(BaseModel):
    """User response schema."""
    id: str
    company_id: str
    email: str
    name: str
    role: str
    is_test: bool
    settings: Optional[dict] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Session Schemas  
# ============================================================================

class SessionCreate(BaseModel):
    """Request to create a new session."""
    pass  # company_id and user_id come from path/headers


class SessionResponse(BaseModel):
    """Session response schema."""
    id: str
    company_id: str
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# CustomerProfile Schemas
# ============================================================================

class CustomerProfileCreate(BaseModel):
    """Request to create a new customer profile."""
    name: str
    title: Optional[str] = None
    customer_company: Optional[str] = None
    industry: Optional[str] = None
    profile_data: Optional[dict] = None


class CustomerProfileUpdate(BaseModel):
    """Request to update a customer profile."""
    name: Optional[str] = None
    title: Optional[str] = None
    customer_company: Optional[str] = None
    industry: Optional[str] = None
    profile_data: Optional[dict] = None


class CustomerProfileResponse(BaseModel):
    """Customer profile response schema."""
    id: str
    company_id: str
    created_by_user_id: str
    name: str
    title: Optional[str] = None
    customer_company: Optional[str] = None
    industry: Optional[str] = None
    profile_data: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Pronunciation Schemas
# ============================================================================

class PronunciationCreate(BaseModel):
    """Request to create a new pronunciation."""
    word: str
    phonetic_spelling: str
    session_id: Optional[str] = None
    always_included: bool = False


class PronunciationUpdate(BaseModel):
    """Request to update a pronunciation."""
    word: Optional[str] = None
    phonetic_spelling: Optional[str] = None
    always_included: Optional[bool] = None


class PronunciationResponse(BaseModel):
    """Pronunciation response schema."""
    id: str
    company_id: str
    created_by_user_id: str
    session_id: Optional[str] = None
    word: str
    phonetic_spelling: str
    always_included: bool
    is_company_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PronunciationGenerationResponse(BaseModel):
    """Response model for pronunciation generation."""
    phonetic_spelling: str
    english_spelling: str


# ============================================================================
# Feedback Schemas
# ============================================================================

class FeedbackCreate(BaseModel):
    """Request to create or update feedback."""
    target_type: str  # "storyboard" | "scene"
    target_id: Optional[str] = None  # scene_id or null
    rating: str  # "up" | "down"
    comment: Optional[str] = None


class FeedbackUpdate(BaseModel):
    """Request to update existing feedback."""
    rating: Optional[str] = None
    comment: Optional[str] = None


class FeedbackResponse(BaseModel):
    """Feedback response schema."""
    id: str
    session_id: str
    company_id: str
    user_id: str
    target_type: str
    target_id: Optional[str] = None
    rating: str
    comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

