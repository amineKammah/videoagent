'use client';

import { useEffect, useRef, useCallback } from 'react';
import { api } from '@/lib/api';
import { useSessionStore } from '@/store/session';

const POLL_INTERVAL = 400; // Match Streamlit's 0.4s interval

export function useEventPolling() {
    const session = useSessionStore(state => state.session);
    const isProcessing = useSessionStore(state => state.isProcessing);
    const eventsCursor = useSessionStore(state => state.eventsCursor);
    const addEvent = useSessionStore(state => state.addEvent);
    const setEventsCursor = useSessionStore(state => state.setEventsCursor);
    const setScenes = useSessionStore(state => state.setScenes);
    const setVideoGenerating = useSessionStore(state => state.setVideoGenerating);
    const setVideoPath = useSessionStore(state => state.setVideoPath);
    const setVideoBrief = useSessionStore(state => state.setVideoBrief);

    const intervalRef = useRef<NodeJS.Timeout | null>(null);

    const pollEvents = useCallback(async () => {
        if (!session?.id) return;

        try {
            const response = await api.getEvents(session.id, eventsCursor);

            if (response.events.length > 0) {
                for (const event of response.events) {
                    addEvent(event);

                    // Handle special event types for real-time updates
                    if (event.type === 'storyboard_update') {
                        // Fetch latest storyboard when updated
                        try {
                            const storyboard = await api.getStoryboard(session.id);
                            if (storyboard.scenes?.length > 0) {
                                setScenes(storyboard.scenes);
                            }
                        } catch (err) {
                            console.error('Failed to fetch storyboard on update:', err);
                        }
                    } else if (event.type === 'video_brief_update') {
                        try {
                            const brief = await api.getVideoBrief(session.id);
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
    }, [session?.id, eventsCursor, addEvent, setEventsCursor, setScenes, setVideoGenerating, setVideoPath, setVideoBrief]);

    useEffect(() => {
        if (isProcessing && session?.id) {
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
    }, [isProcessing, session?.id, pollEvents]);
}
