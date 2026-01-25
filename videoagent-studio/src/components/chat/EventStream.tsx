'use client';

import { useSessionStore } from '@/store/session';
import { EventItem } from './EventItem';
import { useEffect, useState } from 'react';

export function EventStream() {
    const events = useSessionStore(state => state.events);
    const isProcessing = useSessionStore(state => state.isProcessing);
    const clearEvents = useSessionStore(state => state.clearEvents);

    // Track if we should show the "Complete" state briefly
    const [showComplete, setShowComplete] = useState(false);

    // When processing finishes, show complete briefly then hide
    useEffect(() => {
        if (!isProcessing && events.length > 0) {
            setShowComplete(true);
            const timer = setTimeout(() => {
                setShowComplete(false);
                clearEvents();
            }, 2000); // Show "Complete" for 2 seconds then hide
            return () => clearTimeout(timer);
        }
    }, [isProcessing, events.length, clearEvents]);

    // Hide if not processing and no events (or complete timer expired)
    if (!isProcessing && events.length === 0) {
        return null;
    }

    // Also hide if showComplete is false and not processing
    if (!isProcessing && !showComplete) {
        return null;
    }

    // Show last 8 events to avoid overwhelming the UI, filtering out internal events
    const visibleEvents = events
        .filter(e => e.type !== 'video_render_start' && e.type !== 'storyboard_update')
        .slice(-8);

    return (
        <div className="mx-4 mb-4 animate-slide-in">
            <div className="bg-gradient-to-r from-slate-50 to-slate-100 rounded-xl p-4 border border-slate-200 shadow-sm">
                <div className="flex items-center gap-2 mb-3">
                    {isProcessing && (
                        <>
                            <div className="w-2 h-2 bg-teal-500 rounded-full animate-pulse" />
                            <span className="text-xs font-medium text-slate-500 uppercase tracking-wide">
                                Processing
                            </span>
                        </>
                    )}
                    {!isProcessing && showComplete && (
                        <>
                            <div className="w-2 h-2 bg-green-500 rounded-full" />
                            <span className="text-xs font-medium text-green-600 uppercase tracking-wide">
                                Complete
                            </span>
                        </>
                    )}
                </div>

                <div className="space-y-2">
                    {visibleEvents.length === 0 && isProcessing && (
                        <div className="flex items-center gap-2 text-sm text-slate-400">
                            <span className="animate-pulse">⏳</span>
                            <span>Waiting for agent activity...</span>
                        </div>
                    )}
                    {visibleEvents.map((event, index) => (
                        <EventItem
                            key={`${event.ts}-${index}`}
                            event={event}
                            isLatest={index === visibleEvents.length - 1 && isProcessing}
                        />
                    ))}
                </div>
            </div>
        </div>
    );
}
