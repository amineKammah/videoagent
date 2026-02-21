// API Types matching FastAPI backend

export type EventType =
    | 'run_start'
    | 'run_end'
    | 'tool_start'
    | 'tool_end'
    | 'auto_render_start'
    | 'auto_render_end'
    | 'auto_render_skipped'
    | 'segment_warning'
    | 'storyboard_update'
    | 'video_render_start'
    | 'video_render_complete'
    | 'video_brief_update'
    | 'session_title_updated';

export interface AgentEvent {
    ts: string;
    type: EventType;
    name?: string;
    status?: 'ok' | 'error';
    error?: string;
    message?: string;
    title?: string;
    source?: string;
    output?: string;
    input?: unknown;
}

export interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: Date;
    suggestedActions?: string[];
}

// ============================================================================
// Multi-Tenancy Types
// ============================================================================

export interface Company {
    id: string;
    name: string;
    video_library_path?: string;
    is_test: boolean;
    settings: Record<string, unknown>;
    created_at: string;
    updated_at: string;
}

export interface User {
    id: string;
    company_id: string;
    email: string;
    name: string;
    role: 'admin' | 'editor' | 'viewer';
    is_test: boolean;
    settings: Record<string, unknown>;
    created_at: string;
    updated_at: string;
}

export interface VoiceOption {
    id: string;
    name: string;
    gender: 'Male' | 'Female';
    sample_url: string;
}

export interface Session {
    id: string;
    companyId?: string;
    userId?: string;
    createdAt: Date;
    title?: string | null;
}

export interface StoryboardScene {
    scene_id: string;
    title: string;
    purpose: string;
    script: string;
    use_voice_over?: boolean;
    voice_over?: VoiceOver | null;
    matched_scene?: MatchedScene | null;
    order?: number | null;
    // Multi-candidate support
    matched_scene_candidates?: SceneCandidate[];
    selected_candidate_id?: string | null;
    matched_scene_history?: SelectionHistoryEntry[];
    // Animation overlay
    animation?: string | null;
}

export interface MatchedScene {
    segment_type: 'video_clip' | 'title_card';
    source_video_id: string;
    start_time: number;
    end_time: number;
    description: string;
    keep_original_audio: boolean;
}

export interface SceneCandidate {
    candidate_id: string;
    source_video_id: string;
    start_time: number;
    end_time: number;
    description: string;
    rationale: string;
    keep_original_audio: boolean;
    last_rank: number;
    shortlisted: boolean;
    created_at: string;
    updated_at: string;
}

export interface SelectionHistoryEntry {
    entry_id: string;
    candidate_id: string;
    changed_at: string;
    changed_by: 'user' | 'agent';
    reason: string;
}

export interface VoiceOver {
    script: string;
    audio_path?: string;
    audio_url?: string;
    duration?: number;
}

export interface VideoMetadata {
    id: string;
    path: string;
    url?: string;
    filename: string;
    duration: number;
    resolution: [number, number];
    fps: number;
}


export interface VideoBrief {
    video_objective: string;
    persona: string;
    key_messages: string[];
}

// API Response types
export interface ChatResponse {
    session_id: string;
    message: string;
    scenes: StoryboardScene[] | null;
    video_brief?: VideoBrief | null;
    suggested_actions?: string[];
}

export interface EventsResponse {
    session_id: string;
    events: AgentEvent[];
    next_cursor: number;
}

export interface SessionResponse {
    session_id: string;
}

export interface HealthResponse {
    status: string;
}

export interface SessionListItem {
    session_id: string;
    created_at: string;
    title?: string | null;
}

export interface SessionListResponse {
    sessions: SessionListItem[];
}

export interface ChatHistoryMessage {
    role: string;
    content: string;
    timestamp: string;
    suggested_actions?: string[];
}

export interface ChatHistoryResponse {
    session_id: string;
    messages: ChatHistoryMessage[];
}

export interface Customer {
    id: string | number;
    brand_id: number;
    name: string;
    title: string;
    company: string;
    industry: string;
    company_size: string;
    created_at: string;
    [key: string]: unknown;
}

// ============================================================================
// Annotation Types
// ============================================================================

export type SessionStatus = 'pending' | 'reviewed';

export type Severity = 'low' | 'medium' | 'high';

export interface Annotation {
    id: string;
    session_id: string;
    scene_id: string;
    timestamp: number;           // Relative to scene
    global_timestamp: number;    // Absolute in video
    annotator_id: string;
    annotator_name: string;
    category: string;            // Free-text category
    description: string;
    severity: Severity;
    created_at: string;
    updated_at: string;
    resolved: boolean;
    resolved_by?: string;
    rejected?: boolean;
}

export interface CreateAnnotationRequest {
    session_id: string;
    scene_id: string;
    timestamp: number;
    global_timestamp: number;
    annotator_id: string;
    annotator_name: string;
    category: string;
    description: string;
    severity: Severity;
}

export interface UpdateAnnotationRequest {
    category?: string;
    description?: string;
    severity?: Severity;
    resolved?: boolean;
    resolved_by?: string;
}

export interface AnnotationMetrics {
    session_id: string;
    total_annotations: number;
    by_category: Record<string, number>;
    by_scene: Record<string, number>;
    by_severity: Record<Severity, number>;
    faultless_scenes: number;
    total_scenes: number;
}

export type ClusterStatus = 'agreement' | 'conflict' | 'unique';

export interface ClusterResolution {
    accepted_annotation_id: string;
    resolved_by: string;
    resolved_at: string;
    notes?: string;
}

export interface AnnotationCluster {
    id: string;
    scene_id: string;
    center_timestamp: number;
    annotations: Annotation[];
    status: 'agreement' | 'conflict' | 'unique';
    annotator_count: number;
    total_annotators: number;
    resolved: boolean;
    resolution?: ClusterResolution;
}

export interface ComparisonResult {
    session_id: string;
    annotators: string[];
    clusters: AnnotationCluster[];
    stats: {
        total_clusters: number;
        agreements: number;
        conflicts: number;
        unique_annotations: number;
    };
}

// ============================================================================
// Pronunciation Types
// ============================================================================

export interface Pronunciation {
    id: string;
    company_id: string;
    created_by_user_id: string;
    session_id?: string;
    word: string;
    phonetic_spelling: string;
    always_included: boolean;
    is_company_default: boolean;
    created_at: string;
    updated_at: string;
}

export interface CreatePronunciationRequest {
    word: string;
    phonetic_spelling: string;
    session_id?: string;
    always_included?: boolean;
}

// ============================================================================
// Feedback Types
// ============================================================================

export type FeedbackRating = 'up' | 'down';

export interface Feedback {
    id: string;
    session_id: string;
    company_id: string;
    user_id: string;
    target_type: 'storyboard' | 'scene' | 'video_brief';
    target_id: string | null;
    rating: FeedbackRating;
    comment: string | null;
    created_at: string;
    updated_at: string;
}

export interface UpsertFeedbackRequest {
    target_type: 'storyboard' | 'scene' | 'video_brief';
    target_id?: string | null;
    rating: FeedbackRating;
    comment?: string | null;
}
