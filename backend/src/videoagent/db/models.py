"""
SQLAlchemy ORM models for multi-tenancy support.

These models work with SQLite now and can migrate to PostgreSQL later
by changing the DATABASE_URL connection string.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Company(Base):
    """A company/organization using VideoAgent."""
    __tablename__ = "companies"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    video_library_path = Column(String, nullable=True)
    settings = Column(JSON, default=dict)  # Flexible for future fields
    
    # Environment differentiation
    is_test = Column(Boolean, default=True)  # Default to True for now
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    users = relationship("User", back_populates="company", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="company", cascade="all, delete-orphan")


class User(Base):
    """A user within a company."""
    __tablename__ = "users"
    
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, default="editor")  # admin, editor, viewer
    settings = Column(JSON, default=dict)  # User preferences (e.g., tts_voice)
    
    # Allow individual users to be flagged as test users even in prod companies
    is_test = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    company = relationship("Company", back_populates="users")


class Session(Base):
    """A video generation session owned by a user within a company."""
    __tablename__ = "sessions"
    
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Flag to track if the session has any meaningful content (chat (except initial), brief, storyboard)
    has_activity = Column(Boolean, default=False)
    
    # Relationships
    company = relationship("Company", back_populates="sessions")
    user = relationship("User")


class SessionEvent(Base):
    """Append-only event log for a session."""
    __tablename__ = "session_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    session = relationship("Session")
    user = relationship("User")


class SessionStoryboard(Base):
    """Current storyboard state for a session."""
    __tablename__ = "session_storyboards"

    session_id = Column(String, ForeignKey("sessions.id"), primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    scenes = Column(JSON, default=list, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("Session")
    user = relationship("User")


class SessionBrief(Base):
    """Current video brief state for a session."""
    __tablename__ = "session_briefs"

    session_id = Column(String, ForeignKey("sessions.id"), primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    brief = Column(JSON, default=dict, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("Session")
    user = relationship("User")


class SessionChatMessage(Base):
    """Append-only chat history for a session."""
    __tablename__ = "session_chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    suggested_actions = Column(JSON, default=list, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    session = relationship("Session")
    user = relationship("User")


class CustomerProfile(Base):
    """Customer/prospect records - each user manages their own list."""
    __tablename__ = "customer_profiles"
    
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    created_by_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    # Core fields
    name = Column(String, nullable=False)
    title = Column(String)
    customer_company = Column(String)  # The prospect's company name
    industry = Column(String)
    
    # Flexible fields for all the rich data (pain_points, desired_outcomes, etc.)
    profile_data = Column(JSON, default=dict)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    company = relationship("Company")
    created_by = relationship("User")


class Annotation(Base):
    """Video annotations for collaboration and prospect analysis."""
    __tablename__ = "annotations"
    
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    
    # Optional: Link annotation to a specific prospect/customer if relevant
    customer_profile_id = Column(String, ForeignKey("customer_profiles.id"), nullable=True)
    
    scene_id = Column(String, nullable=False)
    timestamp = Column(Float, nullable=False)
    global_timestamp = Column(Float, nullable=False)
    annotator_id = Column(String, nullable=False)  # User ID
    annotator_name = Column(String, nullable=False)
    
    category = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    severity = Column(String, default="medium")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved = Column(Boolean, default=False)
    resolved_by = Column(String, nullable=True)
    rejected = Column(Boolean, default=False)
    
    # Relationships
    company = relationship("Company")
    session = relationship("Session")
    customer_profile = relationship("CustomerProfile")


class SessionAnnotatorStatus(Base):
    """Tracks annotation status per user/annotator for a session."""
    __tablename__ = "session_annotator_status"
    
    session_id = Column(String, ForeignKey("sessions.id"), primary_key=True)
    annotator_id = Column(String, primary_key=True)
    status = Column(String, nullable=False)  # pending, reviewed
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SessionGlobalStatus(Base):
    """Global session status (legacy/backward compatibility)."""
    __tablename__ = "session_status"
    
    session_id = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Pronunciation(Base):
    """Pronunciation guidance for specific words/phrases."""
    __tablename__ = "pronunciations"
    
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    created_by_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True)
    
    word = Column(String, nullable=False)
    phonetic_spelling = Column(String, nullable=False)
    
    # Flags
    always_included = Column(Boolean, default=False)  # User-set global flag
    is_company_default = Column(Boolean, default=False)  # Company-set flag
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    company = relationship("Company")
    created_by = relationship("User")
    session = relationship("Session")


class Feedback(Base):
    """Thumbs up/down feedback on storyboard or individual scenes."""
    __tablename__ = "feedback"

    id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, index=True)
    company_id = Column(String, ForeignKey("companies.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)

    # "storyboard" or "scene"
    target_type = Column(String, nullable=False)
    # scene_id when target_type == "scene"; NULL for storyboard-level
    target_id = Column(String, nullable=True)

    rating = Column(String, nullable=False)  # "up" | "down"
    comment = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    session = relationship("Session", overlaps="session")
    company = relationship("Company")
    user = relationship("User")
