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
    | 'video_render_complete';

export interface AgentEvent {
    ts: string;
    type: EventType;
    name?: string;
    status?: 'ok' | 'error';
    error?: string;
    message?: string;
    output?: string;
    input?: any;
}

export interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: Date;
    suggestedActions?: string[];
}

export interface Session {
    id: string;
    createdAt: Date;
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
}

export interface MatchedScene {
    segment_type: 'video_clip' | 'title_card';
    source_video_id: string;
    start_time: number;
    end_time: number;
    description: string;
    keep_original_audio: boolean;
}

export interface VoiceOver {
    script: string;
    audio_path: string;
    duration: number;
}

export interface VideoMetadata {
    id: string;
    path: string;
    filename: string;
    duration: number;
    resolution: [number, number];
    fps: number;
}

// API Response types
export interface ChatResponse {
    session_id: string;
    message: string;
    scenes: StoryboardScene[] | null;
    customer_details: string | null;
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
