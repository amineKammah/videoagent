// API Types matching FastAPI backend

export type EventType =
  | 'run_start'
  | 'run_end'
  | 'tool_start'
  | 'tool_end'
  | 'auto_render_start'
  | 'auto_render_end'
  | 'auto_render_skipped'
  | 'segment_warning';

export interface AgentEvent {
  ts: string;
  type: EventType;
  name?: string;
  status?: 'ok' | 'error';
  error?: string;
  message?: string;
  output?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
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

// API Response types
export interface ChatResponse {
  session_id: string;
  message: string;
  scenes: StoryboardScene[] | null;
  customer_details: string | null;
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
