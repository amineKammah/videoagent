import {
    ChatResponse,
    ChatHistoryResponse,
    EventsResponse,
    HealthResponse,
    SessionListResponse,
    SessionResponse,
    StoryboardScene,
    VideoMetadata,
    Customer,
    VideoBrief,
    Annotation,
    CreateAnnotationRequest,
    UpdateAnnotationRequest,
    AnnotationMetrics,
    ComparisonResult,
    SessionStatus,
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

    getVideoBrief: async (sessionId: string): Promise<VideoBrief | null> => {
        const response = await fetchWithTimeout(`${API_BASE}/agent/sessions/${sessionId}/brief`);
        return handleResponse<VideoBrief | null>(response);
    },

    updateStoryboard: async (sessionId: string, scenes: StoryboardScene[]): Promise<void> => {
        await fetchWithTimeout(`${API_BASE}/agent/sessions/${sessionId}/storyboard`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scenes }),
        });
    },

    updateSessionStatus: async (sessionId: string, status: SessionStatus, annotatorId?: string): Promise<void> => {
        await fetchWithTimeout(`${API_BASE}/annotations/${sessionId}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status, annotator_id: annotatorId }),
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

    getVideoMetadata: async (videoId: string): Promise<VideoMetadata> => {
        const response = await fetchWithTimeout(`${API_BASE}/agent/library/videos/${videoId}`);
        return handleResponse<VideoMetadata>(response);
    },

    // Customers
    getCustomers: async (): Promise<Customer[]> => {
        const response = await fetchWithTimeout(`${API_BASE}/customers`);
        return handleResponse<Customer[]>(response);
    },

    // ========================================================================
    // Annotations
    // ========================================================================

    getSessionAnnotationCounts: async (): Promise<Record<string, number>> => {
        const response = await fetchWithTimeout(`${API_BASE}/annotations/stats/counts`);
        return handleResponse<Record<string, number>>(response);
    },

    listAnnotations: async (sessionId: string, annotatorId?: string): Promise<Annotation[]> => {
        const url = new URL(`${API_BASE}/annotations/${sessionId}`);
        if (annotatorId) {
            url.searchParams.set('annotator_id', annotatorId);
        }
        const response = await fetchWithTimeout(url.toString());
        const data = await handleResponse<{ annotations: Annotation[] }>(response);
        return data.annotations;
    },

    createAnnotation: async (request: CreateAnnotationRequest): Promise<Annotation> => {
        const response = await fetchWithTimeout(`${API_BASE}/annotations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request),
        });
        return handleResponse<Annotation>(response);
    },

    updateAnnotation: async (id: string, updates: UpdateAnnotationRequest): Promise<Annotation> => {
        const response = await fetchWithTimeout(`${API_BASE}/annotations/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates),
        });
        return handleResponse<Annotation>(response);
    },

    deleteAnnotation: async (id: string): Promise<void> => {
        await fetchWithTimeout(`${API_BASE}/annotations/${id}`, {
            method: 'DELETE',
        });
    },

    getAnnotationMetrics: async (sessionId: string): Promise<AnnotationMetrics> => {
        const response = await fetchWithTimeout(`${API_BASE}/annotations/${sessionId}/metrics`);
        return handleResponse<AnnotationMetrics>(response);
    },

    compareAnnotations: async (sessionId: string, annotatorIds?: string[]): Promise<ComparisonResult> => {
        const url = new URL(`${API_BASE}/annotations/${sessionId}/compare`);
        if (annotatorIds && annotatorIds.length > 0) {
            url.searchParams.set('annotator_ids', annotatorIds.join(','));
        }
        const response = await fetchWithTimeout(url.toString());
        return handleResponse<ComparisonResult>(response);
        return handleResponse<ComparisonResult>(response);
    },

    setSessionStatus: async (sessionId: string, status: SessionStatus): Promise<{ session_id: string, status: SessionStatus }> => {
        const response = await fetchWithTimeout(`${API_BASE}/annotations/${sessionId}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status }),
        });
        return handleResponse(response);
    },

    getSessionStatus: async (sessionId: string): Promise<{ session_id: string, status: SessionStatus }> => {
        const response = await fetchWithTimeout(`${API_BASE}/annotations/${sessionId}/status`);
        return handleResponse(response);
    },

    getAllSessionStatuses: async (): Promise<Record<string, SessionStatus>> => {
        const response = await fetchWithTimeout(`${API_BASE}/annotations/stats/statuses`);
        return handleResponse(response);
    },

    getAllSessionConflicts: async (): Promise<Record<string, number>> => {
        const response = await fetchWithTimeout(`${API_BASE}/annotations/stats/conflicts`);
        return handleResponse(response);
    },

    resolveAnnotations: async (annotationIds: string[], resolvedBy?: string): Promise<{ resolved_count: number }> => {
        const response = await fetchWithTimeout(`${API_BASE}/annotations/resolve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ annotation_ids: annotationIds, resolved_by: resolvedBy }),
        });
        return handleResponse(response);
    },

    rejectAnnotations: async (annotationIds: string[], resolvedBy?: string): Promise<{ rejected_count: number }> => {
        const response = await fetchWithTimeout(`${API_BASE}/annotations/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ annotation_ids: annotationIds, resolved_by: resolvedBy }),
        });
        return handleResponse(response);
    },
};
