import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { api, ApiUtils } from '@/lib/api';
import { AgentEvent, Message, Session, StoryboardScene, VideoBrief, Company, User } from '@/lib/types';

const MAX_STORED_EVENTS = 200;

export function deriveSessionStateFromEvents(events: AgentEvent[]): {
    isProcessing: boolean;
    videoGenerating: boolean;
    videoPath: string | null;
} {
    let lastRunStartIndex = -1;
    let lastRunEndIndex = -1;
    let lastRenderStartIndex = -1;
    let lastRenderEndIndex = -1;
    let latestVideoPath: string | null = null;

    events.forEach((event, index) => {
        if (event.type === 'run_start') {
            lastRunStartIndex = index;
        } else if (event.type === 'run_end') {
            lastRunEndIndex = index;
            lastRenderEndIndex = index;
        } else if (event.type === 'video_render_start' || event.type === 'auto_render_start') {
            lastRenderStartIndex = index;
        } else if (event.type === 'video_render_complete' || event.type === 'auto_render_end') {
            lastRenderEndIndex = index;
            if (event.output) {
                latestVideoPath = event.output;
            }
        }
    });

    return {
        isProcessing: lastRunStartIndex > lastRunEndIndex,
        videoGenerating: lastRenderStartIndex > lastRenderEndIndex,
        videoPath: latestVideoPath,
    };
}

export function selectLatestRunEvents(events: AgentEvent[], maxEvents = MAX_STORED_EVENTS): AgentEvent[] {
    if (events.length === 0) {
        return [];
    }

    let latestRunStartIndex = -1;
    for (let i = events.length - 1; i >= 0; i -= 1) {
        if (events[i].type === 'run_start') {
            latestRunStartIndex = i;
            break;
        }
    }

    const runScopedEvents = latestRunStartIndex >= 0 ? events.slice(latestRunStartIndex) : events;
    return runScopedEvents.slice(-maxEvents);
}

interface SessionStore {
    // State
    session: Session | null;
    company: Company | null;
    user: User | null;
    messages: Message[];
    events: AgentEvent[];
    scenes: StoryboardScene[];
    videoBrief: VideoBrief | null;
    isProcessing: boolean;
    eventsCursor: number | undefined;
    apiHealthy: boolean;
    videoGenerating: boolean;
    videoPath: string | null;

    // Actions
    checkHealth: () => Promise<void>;
    setCompany: (company: Company | null) => void;
    setUser: (user: User | null) => void;
    createSession: () => Promise<string>;
    loadSession: (sessionId: string) => Promise<void>;
    sendMessage: (content: string) => Promise<void>;
    addMessage: (message: Message) => void;
    setMessages: (messages: Message[]) => void;
    addEvent: (event: AgentEvent) => void;
    setEvents: (events: AgentEvent[]) => void;
    setEventsCursor: (cursor: number) => void;
    setScenes: (scenes: StoryboardScene[]) => void;
    setVideoBrief: (brief: VideoBrief | null) => void;
    setProcessing: (isProcessing: boolean) => void;
    setVideoGenerating: (generating: boolean) => void;
    setVideoPath: (path: string | null) => void;
    clearEvents: () => void;
    reset: () => void;
}

export const useSessionStore = create<SessionStore>()(
    persist(
        (set, get) => ({
            // Initial state
            session: null,
            company: null,
            user: null,
            messages: [],
            events: [],
            scenes: [],
            videoBrief: null,
            isProcessing: false,
            eventsCursor: undefined,
            apiHealthy: false,
            videoGenerating: false,
            videoPath: null,

            checkHealth: async () => {
                try {
                    const response = await api.health();
                    set({ apiHealthy: response.status === 'ok' });
                } catch {
                    set({ apiHealthy: false });
                }
            },


            setCompany: (company) => {
                set({ company });
                if (company) {
                    ApiUtils.currentCompanyId = company.id;
                } else {
                    ApiUtils.currentCompanyId = null;
                }
            },

            setUser: (user) => {
                set({ user });
                if (user) {
                    ApiUtils.currentUserId = user.id;
                } else {
                    ApiUtils.currentUserId = null;
                }
            },

            createSession: async () => {
                try {
                    // UserId is now handled by the API client automatically
                    const response = await api.createSession();
                    const newSessionId = response;

                    set({
                        session: { id: newSessionId, createdAt: new Date() },
                        messages: [],
                        events: [],
                        scenes: [],
                        videoBrief: null,
                        isProcessing: false,
                        eventsCursor: undefined,
                    });
                    return newSessionId;
                } catch (error) {
                    console.error('Failed to create session:', error);
                    throw error;
                }
            },

            loadSession: async (sessionId: string) => {
                // First, set the session and clear existing data
                set({
                    session: { id: sessionId, createdAt: new Date() },
                    messages: [],
                    events: [],
                    scenes: [],
                    videoBrief: null,
                    isProcessing: false,
                    eventsCursor: undefined,
                });

                // Fetch the storyboard for this session
                try {
                    const storyboard = await api.getStoryboard(sessionId);
                    if (storyboard.scenes && storyboard.scenes.length > 0) {
                        set({ scenes: storyboard.scenes });
                    }
                } catch (error) {
                    console.error('Failed to load storyboard:', error);
                }

                // Fetch the video brief
                try {
                    const brief = await api.getVideoBrief(sessionId);
                    if (brief) {
                        set({ videoBrief: brief });
                    }
                } catch (error) {
                    console.error('Failed to load video brief:', error);
                }

                // Fetch the chat history for this session
                try {
                    const chatHistory = await api.getChatHistory(sessionId);
                    if (chatHistory.messages && chatHistory.messages.length > 0) {
                        const messages: Message[] = chatHistory.messages.map((m, idx) => ({
                            id: `restored-${idx}`,
                            role: m.role as 'user' | 'assistant',
                            content: m.content,
                            timestamp: new Date(m.timestamp),
                            suggestedActions: m.suggested_actions,
                        }));
                        set({ messages });
                    }
                } catch (error) {
                    console.error('Failed to load chat history:', error);
                }

                // Fetch event history so refresh can recover in-flight runs
                try {
                    const eventsResponse = await api.getEvents(sessionId, 0);
                    const allEvents = eventsResponse.events || [];
                    const derived = deriveSessionStateFromEvents(allEvents);
                    const latestRunEvents = selectLatestRunEvents(allEvents);

                    set({
                        events: latestRunEvents,
                        eventsCursor: eventsResponse.next_cursor,
                        isProcessing: derived.isProcessing,
                        videoGenerating: derived.videoGenerating,
                        videoPath: derived.videoPath,
                    });
                } catch (error) {
                    console.error('Failed to load event history:', error);
                }
            },

            sendMessage: async (content: string) => {
                const { session } = get();
                if (!session) {
                    throw new Error('No active session');
                }

                // Add user message immediately
                const userMessage: Message = {
                    id: crypto.randomUUID(),
                    role: 'user',
                    content,
                    timestamp: new Date(),
                };
                set(state => ({
                    messages: [...state.messages, userMessage],
                    isProcessing: true,
                    events: [],
                    eventsCursor: undefined,
                }));

                try {
                    // Get initial cursor before sending
                    const initialEvents = await api.getEvents(session.id);
                    set({ eventsCursor: initialEvents.next_cursor });

                    // Send message to API
                    const response = await api.sendMessage(session.id, content);

                    // Add assistant response
                    const assistantMessage: Message = {
                        id: crypto.randomUUID(),
                        role: 'assistant',
                        content: response.message,
                        timestamp: new Date(),
                    };

                    set(state => ({
                        messages: [...state.messages, assistantMessage],
                        isProcessing: false,
                        scenes: response.scenes || state.scenes,
                        videoBrief: response.video_brief || state.videoBrief,
                    }));
                } catch (error) {
                    // Add error message
                    const errorMessage: Message = {
                        id: crypto.randomUUID(),
                        role: 'assistant',
                        content: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
                        timestamp: new Date(),
                    };
                    set(state => ({
                        messages: [...state.messages, errorMessage],
                        isProcessing: false,
                    }));
                }
            },

            addMessage: (message: Message) => {
                set(state => ({ messages: [...state.messages, message] }));
            },

            setMessages: (messages: Message[]) => {
                set({ messages });
            },

            addEvent: (event: AgentEvent) => {
                set(state => ({ events: [...state.events, event] }));
            },

            setEvents: (events: AgentEvent[]) => {
                set({ events });
            },

            setEventsCursor: (cursor: number) => {
                set({ eventsCursor: cursor });
            },

            setScenes: (scenes: StoryboardScene[]) => {
                set({ scenes });
            },

            setVideoBrief: (brief: VideoBrief | null) => {
                set({ videoBrief: brief });
            },

            setProcessing: (isProcessing: boolean) => {
                set({ isProcessing });
            },

            setVideoGenerating: (generating: boolean) => {
                set({ videoGenerating: generating });
            },

            setVideoPath: (path: string | null) => {
                set({ videoPath: path });
            },

            clearEvents: () => {
                set({ events: [], eventsCursor: undefined });
            },

            reset: () => {
                set({
                    session: null,
                    company: null,
                    user: null,
                    messages: [],
                    events: [],
                    scenes: [],
                    videoBrief: null,
                    isProcessing: false,
                    eventsCursor: undefined,
                    videoGenerating: false,
                    videoPath: null,
                });
            },
        }),
        {
            name: 'videoagent-session-store',
            storage: createJSONStorage(() => localStorage),
            partialize: (state) => ({
                company: state.company,
                user: state.user
            }),
        }
    )
);
