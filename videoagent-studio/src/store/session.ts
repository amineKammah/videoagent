import { create } from 'zustand';
import { api } from '@/lib/api';
import { AgentEvent, Message, Session, StoryboardScene } from '@/lib/types';

interface SessionStore {
    // State
    session: Session | null;
    messages: Message[];
    events: AgentEvent[];
    scenes: StoryboardScene[];
    customerDetails: string;
    isProcessing: boolean;
    eventsCursor: number | undefined;
    apiHealthy: boolean;

    // Actions
    checkHealth: () => Promise<void>;
    createSession: () => Promise<void>;
    loadSession: (sessionId: string) => void;
    sendMessage: (content: string) => Promise<void>;
    addMessage: (message: Message) => void;
    addEvent: (event: AgentEvent) => void;
    setEvents: (events: AgentEvent[]) => void;
    setEventsCursor: (cursor: number) => void;
    setScenes: (scenes: StoryboardScene[]) => void;
    setCustomerDetails: (details: string) => void;
    setProcessing: (isProcessing: boolean) => void;
    clearEvents: () => void;
    reset: () => void;
}

export const useSessionStore = create<SessionStore>((set, get) => ({
    // Initial state
    session: null,
    messages: [],
    events: [],
    scenes: [],
    customerDetails: '',
    isProcessing: false,
    eventsCursor: undefined,
    apiHealthy: false,

    checkHealth: async () => {
        try {
            const response = await api.health();
            set({ apiHealthy: response.status === 'ok' });
        } catch {
            set({ apiHealthy: false });
        }
    },

    createSession: async () => {
        try {
            const response = await api.createSession();
            set({
                session: { id: response.session_id, createdAt: new Date() },
                messages: [],
                events: [],
                scenes: [],
                customerDetails: '',
                isProcessing: false,
                eventsCursor: undefined,
            });
        } catch (error) {
            console.error('Failed to create session:', error);
            throw error;
        }
    },

    loadSession: (sessionId: string) => {
        set({
            session: { id: sessionId, createdAt: new Date() },
            messages: [],
            events: [],
            scenes: [],
            customerDetails: '',
            isProcessing: false,
            eventsCursor: undefined,
        });
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
                customerDetails: response.customer_details || state.customerDetails,
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

    setCustomerDetails: (details: string) => {
        set({ customerDetails: details });
    },

    setProcessing: (isProcessing: boolean) => {
        set({ isProcessing });
    },

    clearEvents: () => {
        set({ events: [], eventsCursor: undefined });
    },

    reset: () => {
        set({
            session: null,
            messages: [],
            events: [],
            scenes: [],
            customerDetails: '',
            isProcessing: false,
            eventsCursor: undefined,
        });
    },
}));
