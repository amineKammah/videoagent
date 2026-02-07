"""
Annotation models and database operations for video annotations.

This module provides:
- Annotation data models (Pydantic)
- Database CRUD operations for annotations
- Proximity-based clustering for multi-annotator comparison
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, and_, select
from sqlalchemy.orm import Session as DBSession

# Import ORM models
from videoagent.db.models import (
    Annotation as DBAnnotation,
    SessionAnnotatorStatus as DBSessionAnnotatorStatus,
    SessionGlobalStatus as DBSessionGlobalStatus
)


class Severity(str, Enum):
    """Severity level for an annotation."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SessionStatus(str, Enum):
    """Status of the annotation session."""
    PENDING = "pending"
    REVIEWED = "reviewed"


class SessionStatusInfo(BaseModel):
    """Information about a session's annotation status."""
    session_id: str
    status: SessionStatus
    updated_at: datetime


class Annotation(BaseModel):
    """A single annotation on a video at a specific timestamp."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_id: Optional[str] = None  # For multi-tenancy
    session_id: str
    scene_id: str
    timestamp: float  # Relative time within scene (seconds)
    global_timestamp: float  # Absolute time in video
    annotator_id: str
    annotator_name: str
    category: str  # Free-text category
    description: str
    severity: Severity = Severity.MEDIUM
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    resolved: bool = False
    resolved_by: Optional[str] = None
    rejected: bool = False


class CreateAnnotationRequest(BaseModel):
    """Request to create a new annotation."""
    company_id: Optional[str] = None  # For multi-tenancy
    session_id: str
    scene_id: str
    timestamp: float
    global_timestamp: float
    annotator_id: str
    annotator_name: str
    category: str
    description: str
    severity: Severity = Severity.MEDIUM


class UpdateAnnotationRequest(BaseModel):
    """Request to update an existing annotation."""
    category: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[Severity] = None
    resolved: Optional[bool] = None
    resolved_by: Optional[str] = None
    rejected: Optional[bool] = None


class AnnotationMetrics(BaseModel):
    """Aggregated metrics for annotations on a session."""
    total_annotations: int
    by_category: dict[str, int]
    by_scene: dict[str, int]
    by_severity: dict[str, int]
    faultless_scenes: int
    total_scenes: int


class ClusterStatus(str, Enum):
    """Status of an annotation cluster."""
    AGREEMENT = "agreement"
    CONFLICT = "conflict"
    UNIQUE = "unique"


class ClusterResolution(BaseModel):
    """Resolution details for a cluster."""
    accepted_annotation_id: str
    resolved_by: str
    resolved_at: datetime
    notes: Optional[str] = None


class AnnotationCluster(BaseModel):
    """A cluster of annotations from different annotators at similar timestamps."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    scene_id: str
    center_timestamp: float
    annotations: list[Annotation]
    status: ClusterStatus
    resolved: bool = False
    resolution: Optional[ClusterResolution] = None
    annotator_count: int = 0
    total_annotators: int = 0


class ComparisonResult(BaseModel):
    """Result of comparing annotations from multiple annotators."""
    session_id: str
    annotators: list[str]
    clusters: list[AnnotationCluster]
    stats: dict


def _orm_to_model(orm_obj: DBAnnotation) -> Annotation:
    """Convert an ORM object to an Annotation model."""
    return Annotation(
        id=orm_obj.id,
        company_id=orm_obj.company_id,
        session_id=orm_obj.session_id,
        scene_id=orm_obj.scene_id,
        timestamp=orm_obj.timestamp,
        global_timestamp=orm_obj.global_timestamp,
        annotator_id=orm_obj.annotator_id,
        annotator_name=orm_obj.annotator_name,
        category=orm_obj.category,
        description=orm_obj.description,
        severity=Severity(orm_obj.severity),
        created_at=orm_obj.created_at,
        updated_at=orm_obj.updated_at,
        resolved=orm_obj.resolved,
        resolved_by=orm_obj.resolved_by,
        rejected=orm_obj.rejected,
    )


def create_annotation(db: DBSession, request: CreateAnnotationRequest) -> Annotation:
    """Create a new annotation in the database."""
    now = datetime.utcnow()
    annotation_id = str(uuid.uuid4())
    
    db_annotation = DBAnnotation(
        id=annotation_id,
        company_id=request.company_id,
        session_id=request.session_id,
        scene_id=request.scene_id,
        timestamp=request.timestamp,
        global_timestamp=request.global_timestamp,
        annotator_id=request.annotator_id,
        annotator_name=request.annotator_name,
        category=request.category,
        description=request.description,
        severity=request.severity.value,
        created_at=now,
        updated_at=now,
        resolved=False,
        rejected=False
    )
    
    db.add(db_annotation)
    db.commit()
    db.refresh(db_annotation)
    
    return _orm_to_model(db_annotation)


def get_annotation(db: DBSession, annotation_id: str) -> Optional[Annotation]:
    """Get a single annotation by ID."""
    db_annotation = db.query(DBAnnotation).filter(DBAnnotation.id == annotation_id).first()
    if db_annotation:
        return _orm_to_model(db_annotation)
    return None


def list_annotations(
    db: DBSession,
    session_id: str,
    annotator_id: Optional[str] = None,
    include_rejected: bool = False,
) -> list[Annotation]:
    """List all annotations for a session, optionally filtered by annotator."""
    query = db.query(DBAnnotation).filter(DBAnnotation.session_id == session_id)
    
    if annotator_id:
        query = query.filter(DBAnnotation.annotator_id == annotator_id)
        
    if not include_rejected:
        query = query.filter(or_(DBAnnotation.rejected == False, DBAnnotation.rejected == None))
        
    query = query.order_by(DBAnnotation.global_timestamp)
    rows = query.all()
    
    return [_orm_to_model(row) for row in rows]


def update_annotation(
    db: DBSession,
    annotation_id: str,
    request: UpdateAnnotationRequest,
) -> Optional[Annotation]:
    """Update an existing annotation."""
    db_annotation = db.query(DBAnnotation).filter(DBAnnotation.id == annotation_id).first()
    if not db_annotation:
        return None
    
    if request.category is not None:
        db_annotation.category = request.category
    if request.description is not None:
        db_annotation.description = request.description
    if request.severity is not None:
        db_annotation.severity = request.severity.value
    if request.resolved is not None:
        db_annotation.resolved = request.resolved
    if request.resolved_by is not None:
        db_annotation.resolved_by = request.resolved_by
    if request.rejected is not None:
        db_annotation.rejected = request.rejected
    
    db_annotation.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(db_annotation)
    
    return _orm_to_model(db_annotation)


def delete_annotation(db: DBSession, annotation_id: str) -> bool:
    """Delete an annotation by ID."""
    db_annotation = db.query(DBAnnotation).filter(DBAnnotation.id == annotation_id).first()
    if db_annotation:
        db.delete(db_annotation)
        db.commit()
        return True
    return False


def reject_annotations(db: DBSession, annotation_ids: list[str], resolved_by: Optional[str] = None) -> int:
    """Mark annotations as rejected (soft delete)."""
    if not annotation_ids:
        return 0
        
    now = datetime.utcnow()
    
    count = db.query(DBAnnotation).filter(
        DBAnnotation.id.in_(annotation_ids)
    ).update({
        DBAnnotation.rejected: True,
        DBAnnotation.resolved: True,
        DBAnnotation.resolved_by: resolved_by,
        DBAnnotation.updated_at: now
    }, synchronize_session=False)
    
    db.commit()
    return count


def get_all_session_annotation_counts(db: DBSession) -> dict[str, int]:
    """Get total number of annotations for each session."""
    rows = db.query(
        DBAnnotation.session_id, func.count(DBAnnotation.id)
    ).filter(
        or_(DBAnnotation.rejected == False, DBAnnotation.rejected == None)
    ).group_by(DBAnnotation.session_id).all()
    
    return {row[0]: row[1] for row in rows}


def get_annotation_metrics(db: DBSession, session_id: str) -> AnnotationMetrics:
    """Get metrics for a session's annotations."""
    # This reuses the list function which already returns Pydantic models
    annotations = list_annotations(db, session_id)
    
    total = len(annotations)
    by_category = {}
    by_scene = {}
    by_severity = {}
    
    for ann in annotations:
        by_category[ann.category] = by_category.get(ann.category, 0) + 1
        by_scene[ann.scene_id] = by_scene.get(ann.scene_id, 0) + 1
        by_severity[ann.severity.value] = by_severity.get(ann.severity.value, 0) + 1
        
    return AnnotationMetrics(
        total_annotations=total,
        by_category=by_category,
        by_scene=by_scene,
        by_severity=by_severity,
        faultless_scenes=0, # Log parsing logic needed if we want this
        total_scenes=len(by_scene)
    )


def compare_annotations(
    db: DBSession,
    session_id: str,
    annotator_ids: Optional[list[str]] = None,
) -> ComparisonResult:
    """
    Compare annotations from multiple annotators.
    """
    # Get all annotations including rejected
    all_annotations = list_annotations(db, session_id, include_rejected=True)
    
    # Filter by annotator_ids if provided
    if annotator_ids:
        all_annotations = [a for a in all_annotations if a.annotator_id in annotator_ids]
    
    # Get participants who have explicitly set status
    status_rows = db.query(DBSessionAnnotatorStatus.annotator_id).filter(
        DBSessionAnnotatorStatus.session_id == session_id
    ).distinct().all()
    status_annotators = [row[0] for row in status_rows]
    
    # Get unique annotators from annotations
    annotation_annotators = list(set(a.annotator_id for a in all_annotations))
    
    # Full set of participants IDs
    if annotator_ids:
        participant_ids = set(annotator_ids)
    else:
        participant_ids = set(status_annotators) | set(annotation_annotators)
    
    total_annotators = len(participant_ids)
    annotators = list(participant_ids)

    # Group by scene
    by_scene: dict[str, list[Annotation]] = {}
    for ann in all_annotations:
        if ann.scene_id not in by_scene:
            by_scene[ann.scene_id] = []
        by_scene[ann.scene_id].append(ann)
    
    clusters: list[AnnotationCluster] = []
    
    for scene_id, scene_annotations in by_scene.items():
        if not scene_annotations:
            continue
            
        scene_annotations.sort(key=lambda a: a.global_timestamp)
        
        active_annotations = [a for a in scene_annotations if not a.rejected]
        
        scene_annotator_ids = set(a.annotator_id for a in active_annotations)
        annotator_count = len(scene_annotator_ids)
        
        status = ClusterStatus.UNIQUE
        
        if not active_annotations:
            status = ClusterStatus.AGREEMENT
        else:
            if annotator_count < total_annotators:
                 status = ClusterStatus.CONFLICT
            else:
                annotator_counts = {}
                for a in active_annotations:
                    annotator_counts[a.annotator_id] = annotator_counts.get(a.annotator_id, 0) + 1
                
                if any(c > 1 for c in annotator_counts.values()):
                    status = ClusterStatus.CONFLICT
                else:
                    categories = set(a.category.lower() for a in active_annotations)
                    severities = set(a.severity.value for a in active_annotations)
                    if len(categories) == 1 and len(severities) == 1:
                        status = ClusterStatus.AGREEMENT
                    else:
                        status = ClusterStatus.CONFLICT

        target_set = active_annotations if active_annotations else scene_annotations
        center = sum(a.global_timestamp for a in target_set) / len(target_set)
        
        clusters.append(AnnotationCluster(
            scene_id=scene_id,
            center_timestamp=center,
            annotations=scene_annotations,
            status=status,
            annotator_count=annotator_count,
            total_annotators=total_annotators,
        ))
    
    clusters.sort(key=lambda c: c.center_timestamp)
    
    return ComparisonResult(
        session_id=session_id,
        annotators=annotators,
        clusters=clusters,
        stats={
            "total_clusters": len(clusters),
            "agreements": sum(1 for c in clusters if c.status == ClusterStatus.AGREEMENT),
            "conflicts": sum(1 for c in clusters if c.status == ClusterStatus.CONFLICT),
            "unique_annotations": sum(1 for c in clusters if c.status == ClusterStatus.UNIQUE),
        },
    )


def set_session_status(db: DBSession, session_id: str, status: SessionStatus, annotator_id: Optional[str] = None) -> SessionStatusInfo:
    """Set the annotation status for a session. NOW supports per-annotator."""
    now = datetime.utcnow()
    
    # 1. Update Global Status (Legacy/Overall)
    # Using merge for upsert-like behavior
    global_status = db.query(DBSessionGlobalStatus).filter(DBSessionGlobalStatus.session_id == session_id).first()
    if not global_status:
        global_status = DBSessionGlobalStatus(session_id=session_id)
        db.add(global_status)
    
    global_status.status = status.value
    global_status.updated_at = now
    
    # 2. Update Per-Annotator Status if provided
    if annotator_id:
        user_status = db.query(DBSessionAnnotatorStatus).filter(
            DBSessionAnnotatorStatus.session_id == session_id,
            DBSessionAnnotatorStatus.annotator_id == annotator_id
        ).first()
        
        if not user_status:
            user_status = DBSessionAnnotatorStatus(
                session_id=session_id,
                annotator_id=annotator_id
            )
            db.add(user_status)
            
        user_status.status = status.value
        user_status.updated_at = now
    
    db.commit()
    
    return SessionStatusInfo(
        session_id=session_id,
        status=status,
        updated_at=now
    )


def get_session_status(db: DBSession, session_id: str) -> Optional[SessionStatusInfo]:
    """Get the annotation status for a session."""
    row = db.query(DBSessionGlobalStatus).filter(DBSessionGlobalStatus.session_id == session_id).first()
    if row:
        return SessionStatusInfo(
            session_id=row.session_id,
            status=SessionStatus(row.status),
            updated_at=row.updated_at
        )
    return None


def get_all_session_statuses(db: DBSession) -> dict[str, SessionStatus]:
    """Get annotation statuses for all sessions."""
    rows = db.query(DBSessionGlobalStatus).all()
    return {row.session_id: SessionStatus(row.status) for row in rows}


def _is_scene_conflict(scene_annotations: list[Annotation]) -> bool:
    """Check if a group of scene annotations represents a conflict."""
    active = [a for a in scene_annotations if not a.rejected]
    
    if not active:
        return False
        
    annotator_counts = {}
    for a in active:
        annotator_counts[a.annotator_id] = annotator_counts.get(a.annotator_id, 0) + 1
        
    annotator_set = set(annotator_counts.keys())
    
    if len(annotator_set) < 2:
        return False
        
    if any(c > 1 for c in annotator_counts.values()):
        return True
        
    categories = set(a.category.lower() for a in active)
    severities = set(a.severity.value for a in active)
    
    if len(categories) == 1 and len(severities) == 1:
        return False
        
    return True


def get_all_session_conflict_counts(db: DBSession) -> dict[str, int]:
    """Get conflict counts for all sessions."""
    annotations = list_annotations_all(db)
    
    by_session: dict[str, dict[str, list[Annotation]]] = {}
    
    for ann in annotations:
        if ann.rejected:
            continue
            
        if ann.session_id not in by_session:
            by_session[ann.session_id] = {}
            
        if ann.scene_id not in by_session[ann.session_id]:
            by_session[ann.session_id][ann.scene_id] = []
            
        by_session[ann.session_id][ann.scene_id].append(ann)
        
    conflict_counts = {}
    
    for session_id, scenes in by_session.items():
        count = 0
        for scene_anns in scenes.values():
            if _is_scene_conflict(scene_anns):
                count += 1
        if count > 0:
            conflict_counts[session_id] = count
            
    return conflict_counts


def list_annotations_all(db: DBSession) -> list[Annotation]:
    """List ALL annotations across all sessions."""
    rows = db.query(DBAnnotation).order_by(DBAnnotation.session_id, DBAnnotation.scene_id).all()
    return [_orm_to_model(row) for row in rows]


def resolve_annotations(db: DBSession, annotation_ids: list[str], resolved_by: Optional[str] = None) -> int:
    """Mark multiple annotations as resolved."""
    if not annotation_ids:
        return 0
        
    now = datetime.utcnow()
    
    count = db.query(DBAnnotation).filter(
        DBAnnotation.id.in_(annotation_ids)
    ).update({
        DBAnnotation.resolved: True,
        DBAnnotation.resolved_by: resolved_by,
        DBAnnotation.updated_at: now
    }, synchronize_session=False)
    
    db.commit()
    return count
