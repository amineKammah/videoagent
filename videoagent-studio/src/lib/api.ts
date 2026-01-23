import {
    ChatResponse,
    ChatHistoryResponse,
    EventsResponse,
    HealthResponse,
    SessionListResponse,
    SessionResponse,
    StoryboardScene,
    VideoMetadata,
} from './types';


const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Long timeout for LLM calls (10 minutes)
const LLM_TIMEOUT = 10 * 60 * 1000;
// Short timeout for quick calls
const DEFAULT_TIMEOUT = 30 * 1000;

async function fetchWithTimeout(
    url: string,
    options: RequestInit = {},
    timeout: number = DEFAULT_TIMEOUT
): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
        const response = await fetch(url, {
            ...options,
            signal: controller.signal,
        });
        return response;
    } finally {
        clearTimeout(timeoutId);
    }
}

async function handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
        const error = await response.text();
        throw new Error(error || `HTTP ${response.status}`);
    }
    return response.json();
}

export const api = {
    // Health check
    health: async (): Promise<HealthResponse> => {
        const response = await fetchWithTimeout(`${API_BASE}/health`);
        return handleResponse<HealthResponse>(response);
    },

    // Session management
    listSessions: async (): Promise<SessionListResponse> => {
        const response = await fetchWithTimeout(`${API_BASE}/agent/sessions`);
        return handleResponse<SessionListResponse>(response);
    },

    createSession: async (): Promise<SessionResponse> => {
        const response = await fetchWithTimeout(`${API_BASE}/agent/sessions`, {
            method: 'POST',
        });
        return handleResponse<SessionResponse>(response);
    },

    // Chat - send message to LLM (long timeout)
    sendMessage: async (sessionId: string, message: string): Promise<ChatResponse> => {
        const response = await fetchWithTimeout(
            `${API_BASE}/agent/chat`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId, message }),
            },
            LLM_TIMEOUT
        );
        return handleResponse<ChatResponse>(response);
    },

    // Events - poll for streaming updates (short timeout)
    getEvents: async (sessionId: string, cursor?: number): Promise<EventsResponse> => {
        const url = new URL(`${API_BASE}/agent/sessions/${sessionId}/events`);
        if (cursor !== undefined) {
            url.searchParams.set('cursor', cursor.toString());
        }
        const response = await fetchWithTimeout(url.toString(), {}, 10000);
        return handleResponse<EventsResponse>(response);
    },

    // Storyboard
    getStoryboard: async (sessionId: string): Promise<{ scenes: StoryboardScene[] }> => {
        const response = await fetchWithTimeout(`${API_BASE}/agent/sessions/${sessionId}/storyboard`);
        return handleResponse<{ scenes: StoryboardScene[] }>(response);
    },

    // Chat history
    getChatHistory: async (sessionId: string): Promise<ChatHistoryResponse> => {
        const response = await fetchWithTimeout(`${API_BASE}/agent/sessions/${sessionId}/chat`);
        return handleResponse<ChatHistoryResponse>(response);
    },

    updateStoryboard: async (sessionId: string, scenes: StoryboardScene[]): Promise<void> => {
        await fetchWithTimeout(`${API_BASE}/agent/sessions/${sessionId}/storyboard`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scenes }),
        });
    },

    // Draft storyboard from brief (long timeout)
    draftStoryboard: async (sessionId: string, brief: string): Promise<{ scenes: StoryboardScene[] }> => {
        const response = await fetchWithTimeout(
            `${API_BASE}/agent/storyboard/draft`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId, brief }),
            },
            LLM_TIMEOUT
        );
        return handleResponse<{ scenes: StoryboardScene[] }>(response);
    },

    // Render video (long timeout)
    renderVideo: async (sessionId: string): Promise<{ render_result: { success: boolean; output_path?: string; error_message?: string } }> => {
        const response = await fetchWithTimeout(
            `${API_BASE}/agent/sessions/${sessionId}/render`,
            { method: 'POST' },
            LLM_TIMEOUT
        );
        return handleResponse(response);
    },

    // Video Metadata
    getVideoMetadata: async (videoId: string): Promise<VideoMetadata> => {
        const response = await fetchWithTimeout(`${API_BASE}/agent/library/videos/${videoId}`);
        return handleResponse<VideoMetadata>(response);
    },
};

