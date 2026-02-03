"""
CRUD operations for multi-tenancy entities.

This module provides create, read, update, delete operations for
Company, User, and CustomerProfile entities.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session as DBSession

from .models import Company, User, Session, CustomerProfile, Annotation, Pronunciation


# ============================================================================
# Company CRUD
# ============================================================================

def create_company(
    db: DBSession,
    name: str,
    video_library_path: Optional[str] = None,
    is_test: bool = True,
    settings: Optional[dict] = None,
) -> Company:
    """Create a new company."""
    company = Company(
        id=str(uuid.uuid4()),
        name=name,
        video_library_path=video_library_path,
        is_test=is_test,
        settings=settings or {},
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def get_company(db: DBSession, company_id: str) -> Optional[Company]:
    """Get a company by ID."""
    return db.query(Company).filter(Company.id == company_id).first()


def get_company_by_name(db: DBSession, name: str) -> Optional[Company]:
    """Get a company by name."""
    return db.query(Company).filter(Company.name == name).first()


def list_companies(
    db: DBSession,
    include_test: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[Company]:
    """List all companies."""
    query = db.query(Company)
    if not include_test:
        query = query.filter(Company.is_test == False)
    return query.offset(skip).limit(limit).all()


def update_company(
    db: DBSession,
    company_id: str,
    name: Optional[str] = None,
    video_library_path: Optional[str] = None,
    is_test: Optional[bool] = None,
    settings: Optional[dict] = None,
) -> Optional[Company]:
    """Update a company."""
    company = get_company(db, company_id)
    if not company:
        return None
    
    if name is not None:
        company.name = name
    if video_library_path is not None:
        company.video_library_path = video_library_path
    if is_test is not None:
        company.is_test = is_test
    if settings is not None:
        company.settings = settings
    
    company.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(company)
    return company


def delete_company(db: DBSession, company_id: str) -> bool:
    """Delete a company and all associated data."""
    company = get_company(db, company_id)
    if not company:
        return False
    
    db.delete(company)
    db.commit()
    return True


# ============================================================================
# Session CRUD
# ============================================================================

def create_session(
    db: DBSession,
    session_id: str,
    user_id: str,
    company_id: str,
) -> Session:
    """Create a new session."""
    session = Session(
        id=session_id,
        user_id=user_id,
        company_id=company_id,
        created_at=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: DBSession, session_id: str) -> Optional[Session]:
    """Get a session by ID."""
    return db.query(Session).filter(Session.id == session_id).first()


# ============================================================================
# User CRUD
# ============================================================================

def create_user(
    db: DBSession,
    company_id: str,
    email: str,
    name: str,
    role: str = "editor",
    is_test: bool = True,
    settings: Optional[dict] = None,
) -> User:
    """Create a new user in a company."""
    user = User(
        id=str(uuid.uuid4()),
        company_id=company_id,
        email=email,
        name=name,
        role=role,
        is_test=is_test,
        settings=settings or {},
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user(db: DBSession, user_id: str) -> Optional[User]:
    """Get a user by ID."""
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_email(db: DBSession, email: str) -> Optional[User]:
    """Get a user by email."""
    return db.query(User).filter(User.email == email).first()


def list_users(
    db: DBSession,
    company_id: Optional[str] = None,
    include_test: bool = True,
    skip: int = 0,
    limit: int = 100,
) -> list[User]:
    """List users, optionally filtered by company."""
    query = db.query(User)
    if company_id:
        query = query.filter(User.company_id == company_id)
    if not include_test:
        query = query.filter(User.is_test == False)
    return query.offset(skip).limit(limit).all()


def update_user(
    db: DBSession,
    user_id: str,
    name: Optional[str] = None,
    email: Optional[str] = None,
    role: Optional[str] = None,
    is_test: Optional[bool] = None,
    settings: Optional[dict] = None,
) -> Optional[User]:
    """Update a user."""
    user = get_user(db, user_id)
    if not user:
        return None
    
    if name is not None:
        user.name = name
    if email is not None:
        user.email = email
    if role is not None:
        user.role = role
    if is_test is not None:
        user.is_test = is_test
    if settings is not None:
        user.settings = settings
    
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: DBSession, user_id: str) -> bool:
    """Delete a user."""
    user = get_user(db, user_id)
    if not user:
        return False
    
    db.delete(user)
    db.commit()
    return True


# ============================================================================
# Session CRUD
# ============================================================================


def create_session(
    db: DBSession,
    company_id: str,
    user_id: str,
    session_id: Optional[str] = None,
) -> Session:
    """Create a new session for a user in a company."""
    session = Session(
        id=session_id or str(uuid.uuid4()),
        company_id=company_id,
        user_id=user_id,
        has_activity=False,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session



def get_session(db: DBSession, session_id: str) -> Optional[Session]:
    """Get a session by ID."""
    return db.query(Session).filter(Session.id == session_id).first()



def list_sessions(
    db: DBSession,
    company_id: Optional[str] = None,
    user_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    active_only: bool = True,
) -> list[Session]:
    """List sessions, optionally filtered by company and/or user."""
    query = db.query(Session)
    if company_id:
        query = query.filter(Session.company_id == company_id)
    if user_id:
        query = query.filter(Session.user_id == user_id)
    
    if active_only:
        query = query.filter(Session.has_activity == True)
        
    return query.order_by(Session.created_at.desc()).offset(skip).limit(limit).all()



def delete_session(db: DBSession, session_id: str) -> bool:
    """Delete a session."""
    session = get_session(db, session_id)
    if not session:
        return False
    
    db.delete(session)
    db.commit()
    return True


def mark_session_active(db: DBSession, session_id: str) -> Optional[Session]:
    """Mark a session as having activity."""
    session = get_session(db, session_id)
    if session and not session.has_activity:
        session.has_activity = True
        db.commit()
        db.refresh(session)
    return session



# ============================================================================
# CustomerProfile CRUD
# ============================================================================

def create_customer_profile(
    db: DBSession,
    company_id: str,
    created_by_user_id: str,
    name: str,
    title: Optional[str] = None,
    customer_company: Optional[str] = None,
    industry: Optional[str] = None,
    profile_data: Optional[dict] = None,
) -> CustomerProfile:
    """Create a new customer profile."""
    profile = CustomerProfile(
        id=str(uuid.uuid4()),
        company_id=company_id,
        created_by_user_id=created_by_user_id,
        name=name,
        title=title,
        customer_company=customer_company,
        industry=industry,
        profile_data=profile_data or {},
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def get_customer_profile(db: DBSession, profile_id: str) -> Optional[CustomerProfile]:
    """Get a customer profile by ID."""
    return db.query(CustomerProfile).filter(CustomerProfile.id == profile_id).first()


def list_customer_profiles(
    db: DBSession,
    company_id: Optional[str] = None,
    created_by_user_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[CustomerProfile]:
    """List customer profiles, optionally filtered by company and/or user."""
    query = db.query(CustomerProfile)
    if company_id:
        query = query.filter(CustomerProfile.company_id == company_id)
    if created_by_user_id:
        query = query.filter(CustomerProfile.created_by_user_id == created_by_user_id)
    return query.order_by(CustomerProfile.created_at.desc()).offset(skip).limit(limit).all()


def update_customer_profile(
    db: DBSession,
    profile_id: str,
    name: Optional[str] = None,
    title: Optional[str] = None,
    customer_company: Optional[str] = None,
    industry: Optional[str] = None,
    profile_data: Optional[dict] = None,
) -> Optional[CustomerProfile]:
    """Update a customer profile."""
    profile = get_customer_profile(db, profile_id)
    if not profile:
        return None
    
    if name is not None:
        profile.name = name
    if title is not None:
        profile.title = title
    if customer_company is not None:
        profile.customer_company = customer_company
    if industry is not None:
        profile.industry = industry
    if profile_data is not None:
        profile.profile_data = profile_data
    
    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    return profile


def delete_customer_profile(db: DBSession, profile_id: str) -> bool:
    """Delete a customer profile."""
    profile = get_customer_profile(db, profile_id)
    if not profile:
        return False
    
    db.delete(profile)
    db.commit()
    return True


# ============================================================================
# Pronunciation CRUD
# ============================================================================

def create_pronunciation(
    db: DBSession,
    company_id: str,
    created_by_user_id: str,
    word: str,
    phonetic_spelling: str,
    session_id: Optional[str] = None,
    always_included: bool = False,
) -> Pronunciation:
    """Create a new pronunciation guidance."""
    # Enforce limit of 10 "always included" pronunciations per user
    if always_included:
        always_included_count = db.query(Pronunciation).filter(
            Pronunciation.created_by_user_id == created_by_user_id,
            Pronunciation.always_included == True
        ).count()
        if always_included_count >= 10:
            raise ValueError("Limit of 10 'always included' pronunciations reached.")

    pronunciation = Pronunciation(
        id=str(uuid.uuid4()),
        company_id=company_id,
        created_by_user_id=created_by_user_id,
        session_id=session_id,
        word=word,
        phonetic_spelling=phonetic_spelling,
        always_included=always_included,
        is_company_default=False,  # Defaults are set via DB directly for now
    )
    db.add(pronunciation)
    db.commit()
    db.refresh(pronunciation)
    return pronunciation


def get_pronunciation(db: DBSession, pronunciation_id: str) -> Optional[Pronunciation]:
    """Get a pronunciation by ID."""
    return db.query(Pronunciation).filter(Pronunciation.id == pronunciation_id).first()


def list_pronunciations(
    db: DBSession,
    company_id: str,
    user_id: str,
    session_id: str,
) -> list[Pronunciation]:
    """
    List pronunciations relevant to the context.
    Includes:
    - Company defaults
    - User's 'always included' items
    - Current session's items
    """
    from sqlalchemy import or_
    
    filters = [
        # Company defaults
        (Pronunciation.company_id == company_id) & (Pronunciation.is_company_default == True),
        # User's 'always included' items
        (Pronunciation.created_by_user_id == user_id) & (Pronunciation.always_included == True),
        # Session specific items
        Pronunciation.session_id == session_id
    ]
        
    return db.query(Pronunciation).filter(or_(*filters)).all()


def delete_pronunciation(db: DBSession, pronunciation_id: str, user_id: str) -> bool:
    """Delete a pronunciation if owned by the user."""
    pronunciation = get_pronunciation(db, pronunciation_id)
    if not pronunciation or pronunciation.created_by_user_id != user_id:
        return False
    
    if pronunciation.is_company_default:
        # User cannot delete company defaults
        return False
        
    db.delete(pronunciation)
    db.commit()
    return True

