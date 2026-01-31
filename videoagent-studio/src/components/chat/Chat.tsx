'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';

import { useSessionStore } from '@/store/session';
import { useEventPolling } from '@/hooks/useEventPolling';
import { MessageList } from './MessageList';
import { EventStream } from './EventStream';
import { Message } from '@/lib/types';
import { api } from '@/lib/api';

export function Chat() {
    const session = useSessionStore(state => state.session);
    const messages = useSessionStore(state => state.messages);
    const isProcessing = useSessionStore(state => state.isProcessing);
    const setProcessing = useSessionStore(state => state.setProcessing);
    const setScenes = useSessionStore(state => state.setScenes);
    const setVideoBrief = useSessionStore(state => state.setVideoBrief);
    const clearEvents = useSessionStore(state => state.clearEvents);
    const addMessage = useSessionStore(state => state.addMessage);

    const [inputValue, setInputValue] = useState('');
    const [error, setError] = useState<string | null>(null);

    // Auto-send message from URL params
    const searchParams = useSearchParams();
    const router = useRouter();


    // Start polling when processing
    useEventPolling();

    const handleSend = useCallback(async (manualText?: string) => {
        // If manualText is provided, use it. Otherwise use inputValue.
        const content = (typeof manualText === 'string' ? manualText : inputValue).trim();

        if (!session || !content || isProcessing) return;

        setInputValue('');
        setError(null);
        clearEvents();

        // Add user message immediately to store
        const userMessage: Message = {
            id: crypto.randomUUID(),
            role: 'user',
            content,
            timestamp: new Date(),
        };
        addMessage(userMessage);
        setProcessing(true);

        try {
            // Get initial cursor before sending
            try {
                const initialEvents = await api.getEvents(session.id);
                useSessionStore.getState().setEventsCursor(initialEvents.next_cursor);
            } catch (e) {
                console.error('Failed to get initial events cursor:', e);
            }

            // Send message WITHOUT awaiting - let resulting promise handle updates
            api.sendMessage(session.id, content)
                .then(response => {
                    // Add assistant response to store
                    const assistantMessage: Message = {
                        id: crypto.randomUUID(),
                        role: 'assistant',
                        content: response.message,
                        timestamp: new Date(),
                        suggestedActions: response.suggested_actions,
                    };
                    addMessage(assistantMessage);

                    // Update scenes if returned
                    if (response.scenes) {
                        setScenes(response.scenes);
                    }

                    // Update video brief if returned
                    if (response.video_brief) {
                        setVideoBrief(response.video_brief);
                    }
                })
                .catch(err => {
                    const errorMessage = err instanceof Error ? err.message : 'An error occurred';
                    setError(errorMessage);

                    // Add error as assistant message
                    const errorMsg: Message = {
                        id: crypto.randomUUID(),
                        role: 'assistant',
                        content: `Error: ${errorMessage}`,
                        timestamp: new Date(),
                    };
                    addMessage(errorMsg);
                })
                .finally(() => {
                    setProcessing(false);
                });

        } catch (err) {
            console.error(err);
            setProcessing(false);
        }

    }, [session, inputValue, isProcessing, setProcessing, setScenes, setVideoBrief, clearEvents, addMessage]);

    // Check for initial message in URL
    const hasInitialMessageRef = useRef(false);
    useEffect(() => {
        // Get params
        const initialMessage = searchParams.get('initialMessage');
        const urlSessionId = searchParams.get('sessionId');

        // Guard clauses
        if (!session || isProcessing || !initialMessage || hasInitialMessageRef.current) {
            return;
        }

        // CRITICAL: If a specific session ID is requested in URL, ensure we are in that session
        // This prevents a race condition where we send the message to a stale session 
        // before the Sidebar has had a chance to switch to the new one.
        if (urlSessionId && session.id !== urlSessionId) {
            return;
        }

        // Proceed to send
        hasInitialMessageRef.current = true;

        // Remove param from URL without refresh
        const newParams = new URLSearchParams(searchParams.toString());
        newParams.delete('initialMessage');
        router.replace(`?${newParams.toString()}`);

        handleSend(initialMessage);
    }, [session, isProcessing, searchParams, router, handleSend]);

    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    return (
        <div className="flex flex-col flex-1 min-h-0 bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            {/* Header */}
            <div className="px-4 py-2 border-b border-slate-200 bg-slate-50">
                <h2 className="font-semibold text-slate-800">Chat</h2>
                <p className="text-xs text-slate-500">Chat with the LLM to create and edit your storyboard</p>
            </div>

            {/* Messages - Now driven by store state */}
            <MessageList messages={messages} onActionClick={(text) => handleSend(text)} />

            {/* Event Stream - shows during processing */}
            <EventStream />

            {/* Error display */}
            {error && (
                <div className="mx-4 mb-2 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
                    {error}
                </div>
            )}

            {/* Input */}
            <div className="border-t border-slate-200 bg-white p-4">
                <div className="flex items-end gap-3">
                    <textarea
                        value={inputValue}
                        onChange={(e) => setInputValue(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder="Message the LLM..."
                        disabled={isProcessing || !session}
                        rows={1}
                        className="flex-1 resize-none rounded-xl border border-slate-300 bg-slate-50 px-4 py-3 text-sm 
                       placeholder:text-slate-400 focus:border-teal-500 focus:bg-white focus:outline-none 
                       focus:ring-2 focus:ring-teal-500/20 disabled:opacity-50 disabled:cursor-not-allowed
                       transition-all duration-200"
                        style={{ minHeight: '44px', maxHeight: '120px' }}
                    />
                    <button
                        onClick={() => handleSend()}
                        disabled={isProcessing || !session || !inputValue.trim()}
                        className="flex h-11 w-11 items-center justify-center rounded-xl bg-teal-600 text-white 
                       hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors duration-200 shadow-sm hover:shadow-md"
                    >
                        <SendIcon />
                    </button>
                </div>
                {isProcessing && (
                    <p className="text-xs text-slate-400 mt-2 text-center">Processing your request...</p>
                )}
            </div>
        </div>
    );
}

function SendIcon() {
    return (
        <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="w-5 h-5"
        >
            <path d="M3.478 2.405a.75.75 0 00-.926.94l2.432 7.905H13.5a.75.75 0 010 1.5H4.984l-2.432 7.905a.75.75 0 00.926.94 60.519 60.519 0 0018.445-8.986.75.75 0 000-1.218A60.517 60.517 0 003.478 2.405z" />
        </svg>
    );
}
