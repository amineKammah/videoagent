'use client';

import { useEffect, useRef, useCallback } from 'react';
import { useSessionStore } from '@/store/session';
import { api } from '@/lib/api';
import { Message } from '@/lib/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const RECONNECT_DELAY = 3000; // 3 seconds

/**
 * Hook that uses Server-Sent Events (SSE) for real-time event streaming.
 * Replaces the 400ms polling mechanism with push-based updates.
 */
export function useEventStream() {
    const sessionId = useSessionStore(state => state.session?.id);
    const isProcessing = useSessionStore(state => state.isProcessing);
    const eventsCursor = useSessionStore(state => state.eventsCursor);
    const addEvent = useSessionStore(state => state.addEvent);
    const setMessages = useSessionStore(state => state.setMessages);
    const setEventsCursor = useSessionStore(state => state.setEventsCursor);
    const setScenes = useSessionStore(state => state.setScenes);
    const setProcessing = useSessionStore(state => state.setProcessing);
    const setVideoGenerating = useSessionStore(state => state.setVideoGenerating);
    const setVideoPath = useSessionStore(state => state.setVideoPath);
    const setVideoBrief = useSessionStore(state => state.setVideoBrief);

    const eventSourceRef = useRef<EventSource | null>(null);
    const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const connectRef = useRef<(() => void) | null>(null);

    const refreshChatHistory = useCallback(async () => {
        if (!sessionId) return;
        try {
            const chatHistory = await api.getChatHistory(sessionId);
            const messages: Message[] = (chatHistory.messages || []).map((m, idx) => ({
                id: `restored-${idx}`,
                role: m.role as 'user' | 'assistant',
                content: m.content,
                timestamp: new Date(m.timestamp),
                suggestedActions: m.suggested_actions,
            }));
            setMessages(messages);
        } catch (err) {
            console.error('Failed to refresh chat history on run_end:', err);
        }
    }, [sessionId, setMessages]);

    const handleEvent = useCallback(async (event: MessageEvent) => {
        try {
            const data = JSON.parse(event.data);

            // Skip connection events
            if (data.type === 'connected') {
                console.log('[SSE] Connected, cursor:', data.cursor);
                if (typeof data.cursor === 'number') {
                    setEventsCursor(data.cursor);
                }
                return;
            }
            if (data.type === 'cursor') {
                if (typeof data.cursor === 'number') {
                    setEventsCursor(data.cursor);
                }
                return;
            }

            // Add event to store
            addEvent(data);

            // Handle special event types for real-time updates
            if (data.type === 'storyboard_update' && sessionId) {
                try {
                    const storyboard = await api.getStoryboard(sessionId);
                    if (storyboard.scenes?.length > 0) {
                        setScenes(storyboard.scenes);
                    }
                } catch (err) {
                    console.error('Failed to fetch storyboard on update:', err);
                }
            } else if (data.type === 'video_brief_update' && sessionId) {
                try {
                    const brief = await api.getVideoBrief(sessionId);
                    if (brief) {
                        setVideoBrief(brief);
                    }
                } catch (err) {
                    console.error('Failed to fetch video brief on update:', err);
                }
            } else if (data.type === 'video_render_start' || data.type === 'auto_render_start') {
                setVideoGenerating(true);
                setVideoPath(null);
            } else if (data.type === 'run_end') {
                setVideoGenerating(false);
                await refreshChatHistory();
                setProcessing(false);
            } else if (data.type === 'video_render_complete' || data.type === 'auto_render_end') {
                setVideoGenerating(false);
                if (data.output) {
                    setVideoPath(data.output);
                }
            }
        } catch (err) {
            console.error('[SSE] Failed to parse event:', err);
        }
    }, [sessionId, addEvent, refreshChatHistory, setEventsCursor, setProcessing, setScenes, setVideoGenerating, setVideoPath, setVideoBrief]);

    const connect = useCallback(() => {
        if (!sessionId || !isProcessing) return;

        // Close existing connection
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
        }

        const streamUrl = new URL(`${API_BASE}/agent/sessions/${sessionId}/events/stream`);
        if (typeof eventsCursor === 'number') {
            streamUrl.searchParams.set('cursor', String(eventsCursor));
        }
        const url = streamUrl.toString();
        console.log('[SSE] Connecting to:', url, '(cursor:', eventsCursor, ')');

        const eventSource = new EventSource(url);
        eventSourceRef.current = eventSource;

        eventSource.onmessage = handleEvent;

        eventSource.onerror = (error) => {
            console.error('[SSE] Connection error:', error);
            eventSource.close();
            eventSourceRef.current = null;

            // Reconnect after delay if still processing
            reconnectTimeoutRef.current = setTimeout(() => {
                const state = useSessionStore.getState();
                if (state.isProcessing && state.session?.id === sessionId) {
                    console.log(`[SSE] Reconnecting in ${RECONNECT_DELAY}ms...`);
                    connectRef.current?.();
                }
            }, RECONNECT_DELAY);
        };

        eventSource.onopen = () => {
            console.log('[SSE] Connection opened');
        };
    }, [sessionId, isProcessing, eventsCursor, handleEvent]);

    useEffect(() => {
        connectRef.current = connect;
    }, [connect]);

    useEffect(() => {
        if (isProcessing && sessionId) {
            connect();
        } else {
            // Close connection when not processing
            if (eventSourceRef.current) {
                console.log('[SSE] Closing connection (not processing)');
                eventSourceRef.current.close();
                eventSourceRef.current = null;
            }
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
                reconnectTimeoutRef.current = null;
            }
        }

        return () => {
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
                eventSourceRef.current = null;
            }
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
                reconnectTimeoutRef.current = null;
            }
        };
    }, [isProcessing, sessionId, connect]);
}
