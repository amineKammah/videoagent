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

    const intervalRef = useRef<NodeJS.Timeout | null>(null);

    const pollEvents = useCallback(async () => {
        if (!session?.id) return;

        try {
            const response = await api.getEvents(session.id, eventsCursor);

            if (response.events.length > 0) {
                for (const event of response.events) {
                    addEvent(event);
                }
                setEventsCursor(response.next_cursor);
            }
        } catch (error) {
            console.error('Error polling events:', error);
        }
    }, [session?.id, eventsCursor, addEvent, setEventsCursor]);

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
