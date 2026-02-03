'use client';

import { useEffect, useRef, useCallback } from 'react';
import { useSessionStore } from '@/store/session';
import { api } from '@/lib/api';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const RECONNECT_DELAY = 3000; // 3 seconds

/**
 * Hook that uses Server-Sent Events (SSE) for real-time event streaming.
 * Replaces the 400ms polling mechanism with push-based updates.
 */
export function useEventStream() {
    const session = useSessionStore(state => state.session);
    const isProcessing = useSessionStore(state => state.isProcessing);
    const addEvent = useSessionStore(state => state.addEvent);
    const setScenes = useSessionStore(state => state.setScenes);
    const setVideoGenerating = useSessionStore(state => state.setVideoGenerating);
    const setVideoPath = useSessionStore(state => state.setVideoPath);
    const setVideoBrief = useSessionStore(state => state.setVideoBrief);

    const eventSourceRef = useRef<EventSource | null>(null);
    const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

    const handleEvent = useCallback(async (event: MessageEvent) => {
        try {
            const data = JSON.parse(event.data);

            // Skip connection events
            if (data.type === 'connected') {
                console.log('[SSE] Connected, cursor:', data.cursor);
                return;
            }

            // Add event to store
            addEvent(data);

            // Handle special event types for real-time updates
            if (data.type === 'storyboard_update' && session?.id) {
                try {
                    const storyboard = await api.getStoryboard(session.id);
                    if (storyboard.scenes?.length > 0) {
                        setScenes(storyboard.scenes);
                    }
                } catch (err) {
                    console.error('Failed to fetch storyboard on update:', err);
                }
            } else if (data.type === 'video_brief_update' && session?.id) {
                try {
                    const brief = await api.getVideoBrief(session.id);
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
            } else if (data.type === 'video_render_complete' || data.type === 'auto_render_end') {
                setVideoGenerating(false);
                if (data.output) {
                    setVideoPath(data.output);
                }
            }
        } catch (err) {
            console.error('[SSE] Failed to parse event:', err);
        }
    }, [session?.id, addEvent, setScenes, setVideoGenerating, setVideoPath, setVideoBrief]);

    const connect = useCallback(() => {
        if (!session?.id || !isProcessing) return;

        // Close existing connection
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
        }

        const url = `${API_BASE}/agent/sessions/${session.id}/events/stream`;
        console.log('[SSE] Connecting to:', url);

        const eventSource = new EventSource(url);
        eventSourceRef.current = eventSource;

        eventSource.onmessage = handleEvent;

        eventSource.onerror = (error) => {
            console.error('[SSE] Connection error:', error);
            eventSource.close();
            eventSourceRef.current = null;

            // Reconnect after delay if still processing
            if (isProcessing && session?.id) {
                console.log(`[SSE] Reconnecting in ${RECONNECT_DELAY}ms...`);
                reconnectTimeoutRef.current = setTimeout(() => {
                    connect();
                }, RECONNECT_DELAY);
            }
        };

        eventSource.onopen = () => {
            console.log('[SSE] Connection opened');
        };
    }, [session?.id, isProcessing, handleEvent]);

    useEffect(() => {
        if (isProcessing && session?.id) {
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
    }, [isProcessing, session?.id, connect]);
}
