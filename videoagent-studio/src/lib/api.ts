import {
    ChatResponse,
    ChatHistoryResponse,
    EventsResponse,
    HealthResponse,
    SessionListResponse,
    SessionResponse,
    StoryboardScene,
    SceneCandidate,
    SelectionHistoryEntry,
    VideoMetadata,
    Customer,
    VideoBrief,
    Annotation,
    CreateAnnotationRequest,
    UpdateAnnotationRequest,
    AnnotationMetrics,
    ComparisonResult,
    SessionStatus,
    Company,
    User,
    VoiceOption,
    Pronunciation,
    CreatePronunciationRequest,
    Feedback,
    UpsertFeedbackRequest,
} from './types';

export const ApiUtils = {
    currentUserId: null as string | null,
    currentCompanyId: null as string | null
};

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
        const headers = new Headers(options.headers);

        if (ApiUtils.currentUserId) {
            headers.set('X-User-Id', ApiUtils.currentUserId);
            // console.log('[API] Injected X-User-Id:', ApiUtils.currentUserId);
        } else {
            console.warn('[API] Missing X-User-Id! Request may fail.', url);
        }

        if (ApiUtils.currentCompanyId) {
            headers.set('X-Company-ID', ApiUtils.currentCompanyId);
            // console.log('[API] Injected X-Company-ID:', ApiUtils.currentCompanyId);
        } else {
            console.warn('[API] Missing X-Company-ID! Request may fail.', url);
        }

        const response = await fetch(url, {
            ...options,
            headers,
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

    createSession: async (): Promise<string> => {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        // X-User-Id is now injected automatically by fetchWithTimeout

        const response = await fetchWithTimeout(`${API_BASE}/agent/sessions`, {
            method: 'POST',
            headers,
        });
        const data = await handleResponse<{ session_id: string }>(response);
        return data.session_id;
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

    updateVideoBrief: async (sessionId: string, brief: VideoBrief): Promise<VideoBrief> => {
        const response = await fetchWithTimeout(`${API_BASE}/agent/sessions/${sessionId}/brief`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(brief),
        });
        return handleResponse<VideoBrief>(response);
    },

    updateStoryboard: async (sessionId: string, scenes: StoryboardScene[]): Promise<void> => {
        await fetchWithTimeout(`${API_BASE}/agent/sessions/${sessionId}/storyboard`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scenes }),
        });
    },

    // ========================================================================
    // Scene Candidate Selection
    // ========================================================================

    selectCandidate: async (
        sessionId: string,
        sceneId: string,
        candidateId: string,
        reason?: string
    ): Promise<StoryboardScene> => {
        const response = await fetchWithTimeout(
            `${API_BASE}/agent/sessions/${sessionId}/scenes/${sceneId}/select-candidate`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ candidate_id: candidateId, reason: reason || '' }),
            }
        );
        const data = await handleResponse<{ scene: StoryboardScene }>(response);
        return data.scene;
    },

    restoreSelection: async (
        sessionId: string,
        sceneId: string,
        entryId: string,
        reason?: string
    ): Promise<StoryboardScene> => {
        const response = await fetchWithTimeout(
            `${API_BASE}/agent/sessions/${sessionId}/scenes/${sceneId}/restore-selection`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ entry_id: entryId, reason: reason || '' }),
            }
        );
        const data = await handleResponse<{ scene: StoryboardScene }>(response);
        return data.scene;
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

    // ========================================================================
    // Multi-Tenancy - Companies
    // ========================================================================

    listCompanies: async (includeTest: boolean = true): Promise<Company[]> => {
        const url = new URL(`${API_BASE}/api/v1/companies`);
        url.searchParams.set('include_test', includeTest.toString());
        const response = await fetchWithTimeout(url.toString());
        return handleResponse<Company[]>(response);
    },

    createCompany: async (name: string, isTest: boolean = true, settings?: Record<string, any>): Promise<Company> => {
        const response = await fetchWithTimeout(`${API_BASE}/api/v1/companies`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, is_test: isTest, settings }),
        });
        return handleResponse<Company>(response);
    },

    getCompany: async (companyId: string): Promise<Company> => {
        const response = await fetchWithTimeout(`${API_BASE}/api/v1/companies/${companyId}`);
        return handleResponse<Company>(response);
    },

    updateCompany: async (companyId: string, updates: Partial<Company>): Promise<Company> => {
        const response = await fetchWithTimeout(`${API_BASE}/api/v1/companies/${companyId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates),
        });
        return handleResponse<Company>(response);
    },

    deleteCompany: async (companyId: string): Promise<void> => {
        await fetchWithTimeout(`${API_BASE}/api/v1/companies/${companyId}`, { method: 'DELETE' });
    },

    // ========================================================================
    // Multi-Tenancy - Users
    // ========================================================================

    listUsers: async (companyId: string, includeTest: boolean = true): Promise<User[]> => {
        const url = new URL(`${API_BASE}/api/v1/companies/${companyId}/users`);
        url.searchParams.set('include_test', includeTest.toString());
        const response = await fetchWithTimeout(url.toString());
        return handleResponse<User[]>(response);
    },

    createUser: async (companyId: string, email: string, name: string, role: string = 'editor', isTest: boolean = true): Promise<User> => {
        const response = await fetchWithTimeout(`${API_BASE}/api/v1/companies/${companyId}/users`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, name, role, is_test: isTest }),
        });
        return handleResponse<User>(response);
    },

    getUser: async (userId: string): Promise<User> => {
        const response = await fetchWithTimeout(`${API_BASE}/api/v1/users/${userId}`);
        return handleResponse<User>(response);
    },

    updateUser: async (userId: string, updates: Partial<User>): Promise<User> => {
        const response = await fetchWithTimeout(`${API_BASE}/api/v1/users/${userId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates),
        });
        return handleResponse<User>(response);
    },

    deleteUser: async (userId: string): Promise<void> => {
        await fetchWithTimeout(`${API_BASE}/api/v1/users/${userId}`, { method: 'DELETE' });
    },

    // ========================================================================
    // Voice Options
    // ========================================================================

    getVoices: async (): Promise<VoiceOption[]> => {
        const response = await fetchWithTimeout(`${API_BASE}/voices`);
        const data = await handleResponse<{ voices: VoiceOption[] }>(response);
        return data.voices;
    },

    updateUserSettings: async (userId: string, settings: Record<string, any>): Promise<User> => {
        const response = await fetchWithTimeout(`${API_BASE}/api/v1/users/${userId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ settings }),
        });
        return handleResponse<User>(response);
    },

    // ========================================================================
    // Pronunciations
    // ========================================================================

    listPronunciations: async (sessionId: string): Promise<Pronunciation[]> => {
        const url = new URL(`${API_BASE}/api/v1/pronunciations`);
        url.searchParams.set('session_id', sessionId);
        const response = await fetchWithTimeout(url.toString());
        return handleResponse<Pronunciation[]>(response);
    },

    createPronunciation: async (request: CreatePronunciationRequest): Promise<Pronunciation> => {
        const response = await fetchWithTimeout(`${API_BASE}/api/v1/pronunciations`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request),
        });
        return handleResponse<Pronunciation>(response);
    },

    deletePronunciation: async (id: string): Promise<void> => {
        await fetchWithTimeout(`${API_BASE}/api/v1/pronunciations/${id}`, {
            method: 'DELETE',
        });
    },

    generatePronunciation: async (audioShort: Blob, filename: string): Promise<{ phonetic_spelling: string; english_spelling: string }> => {
        const formData = new FormData();
        formData.append('file', audioShort, filename);

        const response = await fetchWithTimeout(`${API_BASE}/api/v1/pronunciations/generate`, {
            method: 'POST',
            body: formData,
        });
        return handleResponse<{ phonetic_spelling: string; english_spelling: string }>(response);
    },

    // ========================================================================
    // Feedback
    // ========================================================================

    upsertFeedback: async (sessionId: string, request: UpsertFeedbackRequest): Promise<Feedback> => {
        const url = new URL(`${API_BASE}/api/v1/feedback`);
        url.searchParams.set('session_id', sessionId);
        const response = await fetchWithTimeout(url.toString(), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request),
        });
        return handleResponse<Feedback>(response);
    },

    listFeedback: async (sessionId: string, targetType?: string, targetId?: string): Promise<Feedback[]> => {
        const url = new URL(`${API_BASE}/api/v1/feedback`);
        url.searchParams.set('session_id', sessionId);
        if (targetType) url.searchParams.set('target_type', targetType);
        if (targetId) url.searchParams.set('target_id', targetId);
        const response = await fetchWithTimeout(url.toString());
        return handleResponse<Feedback[]>(response);
    },

    deleteFeedback: async (id: string): Promise<void> => {
        await fetchWithTimeout(`${API_BASE}/api/v1/feedback/${id}`, {
            method: 'DELETE',
        });
    },
};
