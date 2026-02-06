'use client';

import { useEffect, useRef, useCallback } from 'react';
import { api } from '@/lib/api';
import { useSessionStore } from '@/store/session';
import { Message } from '@/lib/types';

const POLL_INTERVAL = 400; // Match Streamlit's 0.4s interval

export function useEventPolling() {
    const sessionId = useSessionStore(state => state.session?.id);
    const isProcessing = useSessionStore(state => state.isProcessing);
    const eventsCursor = useSessionStore(state => state.eventsCursor);
    const addEvent = useSessionStore(state => state.addEvent);
    const setMessages = useSessionStore(state => state.setMessages);
    const setEventsCursor = useSessionStore(state => state.setEventsCursor);
    const setProcessing = useSessionStore(state => state.setProcessing);
    const setScenes = useSessionStore(state => state.setScenes);
    const setVideoGenerating = useSessionStore(state => state.setVideoGenerating);
    const setVideoPath = useSessionStore(state => state.setVideoPath);
    const setVideoBrief = useSessionStore(state => state.setVideoBrief);

    const intervalRef = useRef<NodeJS.Timeout | null>(null);

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

    const pollEvents = useCallback(async () => {
        if (!sessionId) return;

        try {
            const response = await api.getEvents(sessionId, eventsCursor);

            if (response.events.length > 0) {
                for (const event of response.events) {
                    addEvent(event);

                    // Handle special event types for real-time updates
                    if (event.type === 'storyboard_update') {
                        // Fetch latest storyboard when updated
                        try {
                            const storyboard = await api.getStoryboard(sessionId);
                            if (storyboard.scenes?.length > 0) {
                                setScenes(storyboard.scenes);
                            }
                        } catch (err) {
                            console.error('Failed to fetch storyboard on update:', err);
                        }
                    } else if (event.type === 'video_brief_update') {
                        try {
                            const brief = await api.getVideoBrief(sessionId);
                            if (brief) {
                                setVideoBrief(brief);
                            }
                        } catch (err) {
                            console.error('Failed to fetch video brief on update:', err);
                        }
                    } else if (event.type === 'video_render_start' || event.type === 'auto_render_start') {
                        setVideoGenerating(true);
                        setVideoPath(null);
                    } else if (event.type === 'run_end') {
                        setVideoGenerating(false);
                        await refreshChatHistory();
                        setProcessing(false);
                    } else if (event.type === 'video_render_complete' || event.type === 'auto_render_end') {
                        setVideoGenerating(false);
                        if (event.output) {
                            setVideoPath(event.output);
                        }
                    }
                }
                setEventsCursor(response.next_cursor);
            }
        } catch (error) {
            console.error('Error polling events:', error);
        }
    }, [sessionId, eventsCursor, addEvent, refreshChatHistory, setEventsCursor, setProcessing, setScenes, setVideoGenerating, setVideoPath, setVideoBrief]);

    useEffect(() => {
        if (isProcessing && sessionId) {
            // Start polling
            intervalRef.current = setInterval(pollEvents, POLL_INTERVAL);
            // Poll immediately
            pollEvents();
        } else {
            // Stop polling
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
                intervalRef.current = null;
            }
        }

        return () => {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
            }
        };
    }, [isProcessing, sessionId, pollEvents]);
}
