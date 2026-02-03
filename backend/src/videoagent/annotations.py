"""
Annotation models and database operations for video annotations.

This module provides:
- Annotation data models (Pydantic)
- Database CRUD operations for annotations
- Proximity-based clustering for multi-annotator comparison
"""
import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from videoagent.database import get_db_connection


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


def init_annotations_table():
    """Create the annotations table if it doesn't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT PRIMARY KEY,
            company_id TEXT,
            session_id TEXT NOT NULL,
            scene_id TEXT NOT NULL,
            timestamp REAL NOT NULL,
            global_timestamp REAL NOT NULL,
            annotator_id TEXT NOT NULL,
            annotator_name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved INTEGER DEFAULT 0,
            resolved_by TEXT,
            rejected INTEGER DEFAULT 0
        )
    """)
    
    # Create indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_annotations_session 
        ON annotations(session_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_annotations_annotator 
        ON annotations(session_id, annotator_id)
    """)
    
    # Create session_annotator_status table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_annotator_status (
            session_id TEXT NOT NULL,
            annotator_id TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (session_id, annotator_id)
        )
    """)

    # Keep global session_status for backward compat if needed, or migration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_status (
            session_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()


def _row_to_annotation(row: sqlite3.Row) -> Annotation:
    """Convert a database row to an Annotation model."""
    rejected = False
    if "rejected" in row.keys():
         rejected = bool(row["rejected"])
    
    company_id = None
    if "company_id" in row.keys():
        company_id = row["company_id"]
         
    return Annotation(
        id=row["id"],
        company_id=company_id,
        session_id=row["session_id"],
        scene_id=row["scene_id"],
        timestamp=row["timestamp"],
        global_timestamp=row["global_timestamp"],
        annotator_id=row["annotator_id"],
        annotator_name=row["annotator_name"],
        category=row["category"],
        description=row["description"],
        severity=Severity(row["severity"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        resolved=bool(row["resolved"]),
        resolved_by=row["resolved_by"],
        rejected=rejected,
    )

def create_annotation(request: CreateAnnotationRequest) -> Annotation:
    """Create a new annotation in the database."""
    now = datetime.utcnow()
    annotation = Annotation(
        company_id=request.company_id,
        session_id=request.session_id,
        scene_id=request.scene_id,
        timestamp=request.timestamp,
        global_timestamp=request.global_timestamp,
        annotator_id=request.annotator_id,
        annotator_name=request.annotator_name,
        category=request.category,
        description=request.description,
        severity=request.severity,
        created_at=now,
        updated_at=now,
    )
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO annotations (
            id, company_id, session_id, scene_id, timestamp, global_timestamp,
            annotator_id, annotator_name, category, description, severity,
            created_at, updated_at, resolved, resolved_by, rejected
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        annotation.id,
        annotation.company_id,
        annotation.session_id,
        annotation.scene_id,
        annotation.timestamp,
        annotation.global_timestamp,
        annotation.annotator_id,
        annotation.annotator_name,
        annotation.category,
        annotation.description,
        annotation.severity.value,
        annotation.created_at.isoformat(),
        annotation.updated_at.isoformat(),
        0,
        None,
        0
    ))
    
    conn.commit()
    conn.close()
    
    return annotation


def get_annotation(annotation_id: str) -> Optional[Annotation]:
    """Get a single annotation by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return _row_to_annotation(row)
    return None



def get_annotation(annotation_id: str) -> Optional[Annotation]:
    """Get a single annotation by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return _row_to_annotation(row)
    return None


def list_annotations(
    session_id: str,
    annotator_id: Optional[str] = None,
    include_rejected: bool = False,
) -> list[Annotation]:
    """List all annotations for a session, optionally filtered by annotator."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM annotations WHERE session_id = ?"
    params = [session_id]
    
    if annotator_id:
        query += " AND annotator_id = ?"
        params.append(annotator_id)
        
    if not include_rejected:
        # Check if column exists first? 
        # Assuming schema is migrated.
        query += " AND (rejected = 0 OR rejected IS NULL)"
        
    query += " ORDER BY global_timestamp"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [_row_to_annotation(row) for row in rows]


def update_annotation(
    annotation_id: str,
    request: UpdateAnnotationRequest,
) -> Optional[Annotation]:
    """Update an existing annotation."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build update query dynamically based on provided fields
    updates = []
    values = []
    
    if request.category is not None:
        updates.append("category = ?")
        values.append(request.category)
    if request.description is not None:
        updates.append("description = ?")
        values.append(request.description)
    if request.severity is not None:
        updates.append("severity = ?")
        values.append(request.severity.value)
    if request.resolved is not None:
        updates.append("resolved = ?")
        values.append(1 if request.resolved else 0)
    if request.resolved_by is not None:
        updates.append("resolved_by = ?")
        values.append(request.resolved_by)
    if request.rejected is not None:
        updates.append("rejected = ?")
        values.append(1 if request.rejected else 0)
    
    if not updates:
        conn.close()
        return get_annotation(annotation_id)
    
    updates.append("updated_at = ?")
    values.append(datetime.utcnow().isoformat())
    values.append(annotation_id)
    
    cursor.execute(
        f"UPDATE annotations SET {', '.join(updates)} WHERE id = ?",
        values
    )
    
    conn.commit()
    conn.close()
    
    return get_annotation(annotation_id)

    return get_annotation(annotation_id)


def delete_annotation(annotation_id: str) -> bool:
    """Delete an annotation by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
    deleted = cursor.rowcount > 0
    
    conn.commit()
    conn.close()
    
    return deleted

def reject_annotations(annotation_ids: list[str], resolved_by: Optional[str] = None) -> int:
    """Mark annotations as rejected (soft delete)."""
    if not annotation_ids:
        return 0
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    placeholders = ','.join('?' * len(annotation_ids))
    now = datetime.utcnow().isoformat()
    
    values = [1, 1, resolved_by, now]
    values.extend(annotation_ids)
    
    # Rejected implies resolved (closed issue)
    cursor.execute(f"""
        UPDATE annotations 
        SET rejected = ?, resolved = ?, resolved_by = ?, updated_at = ?
        WHERE id IN ({placeholders})
    """, values)
    
    count = cursor.rowcount
    conn.commit()
    conn.close()
    
    return count

    return count


def get_all_session_annotation_counts() -> dict[str, int]:
    """Get total number of annotations for each session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT session_id, COUNT(*) as count 
        FROM annotations 
        WHERE (rejected = 0 OR rejected IS NULL)
        GROUP BY session_id
    """)
    rows = cursor.fetchall()
    conn.close()
    
    return {row["session_id"]: row["count"] for row in rows}


def get_annotation_metrics(session_id: str) -> AnnotationMetrics:
    """Get metrics for a session's annotations."""
    annotations = list_annotations(session_id)
    
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
    session_id: str,
    annotator_ids: Optional[list[str]] = None,
) -> ComparisonResult:
    """
    Compare annotations from multiple annotators.
    Returns ALL annotations (including rejected) for history.
    Status is determined by ACTIVE (non-rejected) annotations.
    """
    # Get all annotations including rejected
    all_annotations = list_annotations(session_id, include_rejected=True)
    
    # Filter by annotator_ids if provided
    if annotator_ids:
        all_annotations = [a for a in all_annotations if a.annotator_id in annotator_ids]
    
    # Calculate total participants (Union of those who Annotated AND those who explicitly marked status)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT annotator_id FROM session_annotator_status WHERE session_id = ?", (session_id,))
    status_annotators = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    # Get unique annotators from annotations
    annotation_annotators = list(set(a.annotator_id for a in all_annotations)) # Use ID not Name
    
    # Full set of participants IDs
    # If filter provided, start with that. Else union of all sources.
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
        
        # Determine status based on ACTIVE annotations only
        active_annotations = [a for a in scene_annotations if not a.rejected]
        
        # Calculate participation
        scene_annotator_ids = set(a.annotator_id for a in active_annotations) # Use ID
        annotator_count = len(scene_annotator_ids)
        # total_annotators already calculated
        
        status = ClusterStatus.UNIQUE
        
        if not active_annotations:
            # All rejected
            status = ClusterStatus.AGREEMENT
        else:
            # Presence Check: If not all annotators are present, it's a conflict
            if annotator_count < total_annotators:
                 status = ClusterStatus.CONFLICT
            else:
                # All present. Check Content Match.
                annotator_counts = {}
                for a in active_annotations:
                    annotator_counts[a.annotator_id] = annotator_counts.get(a.annotator_id, 0) + 1
                
                # Check for multiple annotations from same person (conflict)
                if any(c > 1 for c in annotator_counts.values()):
                    status = ClusterStatus.CONFLICT
                else:
                    # Check Content Equality
                    categories = set(a.category.lower() for a in active_annotations)
                    severities = set(a.severity.value for a in active_annotations)
                    if len(categories) == 1 and len(severities) == 1:
                        status = ClusterStatus.AGREEMENT
                    else:
                        status = ClusterStatus.CONFLICT

        # Center uses all annotations range? Or just active?
        # Use active if available, else all.
        target_set = active_annotations if active_annotations else scene_annotations
        center = sum(a.global_timestamp for a in target_set) / len(target_set)
        
        clusters.append(AnnotationCluster(
            scene_id=scene_id,
            center_timestamp=center,
            annotations=scene_annotations, # Return ALL (history)
            status=status,
            annotator_count=annotator_count,
            total_annotators=total_annotators,
        ))
    
    # Sort clusters
    clusters.sort(key=lambda c: c.center_timestamp)
    
    # Calculate stats (based on active clusters?)
    # or conflicting clusters.
    
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


def set_session_status(session_id: str, status: SessionStatus, annotator_id: Optional[str] = None) -> SessionStatusInfo:
    """Set the annotation status for a session. NOW supports per-annotator."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.utcnow().isoformat()
    
    # 1. Update Global Status (Legacy/Overall)
    cursor.execute("""
        INSERT INTO session_status (session_id, status, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
    """, (session_id, status.value, now))
    
    # 2. Update Per-Annotator Status if provided
    if annotator_id:
        cursor.execute("""
            INSERT INTO session_annotator_status (session_id, annotator_id, status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id, annotator_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
        """, (session_id, annotator_id, status.value, now))
    
    conn.commit()
    conn.close()
    
    return SessionStatusInfo(
        session_id=session_id,
        status=status,
        updated_at=datetime.fromisoformat(now)
    )


def get_session_status(session_id: str) -> Optional[SessionStatusInfo]:
    """Get the annotation status for a session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM session_status WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return SessionStatusInfo(
            session_id=row["session_id"],
            status=SessionStatus(row["status"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )
    return None


def get_all_session_statuses() -> dict[str, SessionStatus]:
    """Get annotation statuses for all sessions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT session_id, status FROM session_status")
    rows = cursor.fetchall()
    conn.close()
    
    return {row["session_id"]: SessionStatus(row["status"]) for row in rows}


    return {row["session_id"]: row["count"] for row in rows}


def _is_scene_conflict(scene_annotations: list[Annotation]) -> bool:
    """Check if a group of scene annotations represents a conflict."""
    # Filter active only
    active = [a for a in scene_annotations if not a.rejected]
    
    if not active:
        return False
        
    annotator_counts = {}
    for a in active:
        annotator_counts[a.annotator_id] = annotator_counts.get(a.annotator_id, 0) + 1
        
    annotator_set = set(annotator_counts.keys())
    
    # Needs multiple annotators to be a conflict
    if len(annotator_set) < 2:
        return False
        
    # Check for count mismatch (must be 1-to-1)
    if any(c > 1 for c in annotator_counts.values()):
        return True
        
    # Check for content mismatch (Category + Severity)
    categories = set(a.category.lower() for a in active)
    severities = set(a.severity.value for a in active)
    
    if len(categories) == 1 and len(severities) == 1:
        return False # Agreement
        
    return True # Content Disagreement


def get_all_session_conflict_counts() -> dict[str, int]:
    """Get conflict counts for all sessions."""
    # This is a bit expensive, but fine for prototype scale.
    # Optimization: perform this in SQL? Complex logic makes it hard.
    # We'll fetch all active annotations and process in python.
    annotations = list_annotations_all() 
    
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


def list_annotations_all() -> list[Annotation]:
    """List ALL annotations across all sessions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM annotations ORDER BY session_id, scene_id")
    rows = cursor.fetchall()
    conn.close()
    return [_row_to_annotation(row) for row in rows]


def resolve_annotations(annotation_ids: list[str], resolved_by: Optional[str] = None) -> int:
    """Mark multiple annotations as resolved."""
    if not annotation_ids:
        return 0
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    placeholders = ','.join('?' * len(annotation_ids))
    now = datetime.utcnow().isoformat()
    
    values = [1, resolved_by, now]
    values.extend(annotation_ids)
    
    cursor.execute(f"""
        UPDATE annotations 
        SET resolved = ?, resolved_by = ?, updated_at = ?
        WHERE id IN ({placeholders})
    """, values)
    
    count = cursor.rowcount
    conn.commit()
    conn.close()
    
    return count
