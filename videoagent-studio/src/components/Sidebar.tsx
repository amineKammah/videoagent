'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSessionStore } from '@/store/session';
import { useSearchParams, useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { SessionListItem } from '@/lib/types';


export function Sidebar() {
    const session = useSessionStore(state => state.session);
    const user = useSessionStore(state => state.user);
    const apiHealthy = useSessionStore(state => state.apiHealthy);
    const messageCount = useSessionStore(state => state.messages.length);
    const createSession = useSessionStore(state => state.createSession);
    const loadSession = useSessionStore(state => state.loadSession);


    const [isCreating, setIsCreating] = useState(false);
    const [isCollapsed, setIsCollapsed] = useState(true);
    const [sessions, setSessions] = useState<SessionListItem[]>([]);
    const titleRefreshAttemptsRef = useRef(0);

    const searchParams = useSearchParams();
    const router = useRouter();

    const navigateToSession = useCallback((sessionId: string) => {
        router.push(`/studio?sessionId=${encodeURIComponent(sessionId)}`);
    }, [router]);

    const fetchSessions = useCallback(async () => {
        try {
            const response = await api.listSessions();
            setSessions(response.sessions);
        } catch (error) {
            console.error('Failed to fetch sessions:', error);
        }
    }, []);

    // Fetch sessions when API/user/session state changes.
    useEffect(() => {
        if (apiHealthy && user) {
            void fetchSessions();
        } else {
            setSessions([]);
        }
    }, [apiHealthy, user, messageCount, session?.id, fetchSessions]);

    // If the current session is missing from the list (e.g. just created),
    // retry shortly so it appears without a full page refresh.
    useEffect(() => {
        if (!apiHealthy || !user || !session?.id) return;
        if (sessions.some(s => s.session_id === session.id)) return;

        const retryTimer = setTimeout(() => {
            void fetchSessions();
        }, 1200);

        return () => clearTimeout(retryTimer);
    }, [apiHealthy, user, session?.id, sessions, fetchSessions]);

    // Session titles are generated asynchronously on the backend.
    // Retry session list fetch a few times after the first messages so
    // the auto-generated title appears without manual refresh.
    useEffect(() => {
        if (!apiHealthy || !user || !session?.id) return;
        if (messageCount === 0) return;

        const currentSession = sessions.find(s => s.session_id === session.id);
        if (!currentSession) return;

        const hasTitle = Boolean(currentSession.title?.trim());
        if (hasTitle) {
            titleRefreshAttemptsRef.current = 0;
            return;
        }

        if (titleRefreshAttemptsRef.current >= 8) return;

        const retryTimer = setTimeout(() => {
            titleRefreshAttemptsRef.current += 1;
            void fetchSessions();
        }, 1500);

        return () => clearTimeout(retryTimer);
    }, [apiHealthy, user, session?.id, sessions, messageCount, fetchSessions]);

    // Load session from URL if present
    useEffect(() => {
        const sessionId = searchParams.get('sessionId');
        if (sessionId && apiHealthy) {
            // If we have a session ID in URL, load it
            // Only if it's different from current
            if (session?.id !== sessionId) {
                loadSession(sessionId);
            }
        }
    }, [apiHealthy, loadSession, searchParams, session]); // Check when these change

    const handleNewSession = useCallback(async () => {
        setIsCreating(true);
        try {
            const newSessionId = await createSession();
            navigateToSession(newSessionId);
        } catch (error) {
            console.error('Failed to create session:', error);
        } finally {
            setIsCreating(false);
        }
    }, [createSession, navigateToSession]);

    // Auto-create session if API is healthy and no session exists AND no session in URL
    useEffect(() => {
        const sessionIdParam = searchParams.get('sessionId');
        if (apiHealthy && !session && !isCreating && !sessionIdParam) {
            void handleNewSession();
        }
    }, [apiHealthy, handleNewSession, isCreating, searchParams, session]);

    const handleSelectSession = (sessionId: string) => {
        loadSession(sessionId);
        navigateToSession(sessionId);
    };

    const formatDate = (dateStr: string) => {
        const date = new Date(dateStr);
        return date.toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    };

    const formatSessionLabel = (sessionItem: SessionListItem) => {
        const title = sessionItem.title?.trim();
        if (title) return title;
        return `${sessionItem.session_id.slice(0, 12)}...`;
    };

    const visibleSessions = useMemo(() => {
        if (!session) return sessions;
        if (sessions.some(s => s.session_id === session.id)) return sessions;

        return [
            {
                session_id: session.id,
                created_at: session.createdAt?.toISOString?.() ?? new Date().toISOString(),
                title: session.title ?? 'New session',
            },
            ...sessions,
        ];
    }, [session, sessions]);

    const currentSessionItem = visibleSessions.find(s => s.session_id === session?.id);

    if (isCollapsed) {
        return (
            <aside className="w-12 bg-white border-r border-slate-200 flex flex-col items-center py-4">
                <button
                    onClick={() => setIsCollapsed(false)}
                    className="p-2 hover:bg-slate-100 rounded-lg transition-colors"
                    title="Expand sidebar"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5 text-slate-600">
                        <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
                    </svg>
                </button>
                <div className="mt-4">
                    <div
                        className={`w-2 h-2 rounded-full ${apiHealthy ? 'bg-green-500' : 'bg-red-500'}`}
                        title={apiHealthy ? 'API Connected' : 'API Disconnected'}
                    />
                </div>
            </aside>
        );
    }

    return (
        <aside className="w-64 bg-white border-r border-slate-200 flex flex-col">
            {/* Logo + Collapse */}
            <div className="p-4 border-b border-slate-200 flex items-start justify-between">
                <div>
                    <h1 className="text-xl font-bold text-slate-800 font-serif">
                        VideoAgent Studio
                    </h1>
                    <p className="text-xs text-slate-500 mt-1">
                        AI-powered video creation
                    </p>
                    {user && (
                        <p className="text-[10px] text-slate-400 mt-0.5 truncate max-w-[150px]" title={user.email}>
                            {user.email}
                        </p>
                    )}
                </div>
                <button
                    onClick={() => setIsCollapsed(true)}
                    className="p-1 hover:bg-slate-100 rounded transition-colors"
                    title="Collapse sidebar"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 text-slate-400">
                        <path fillRule="evenodd" d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z" clipRule="evenodd" />
                    </svg>
                </button>
            </div>

            {/* Session Controls */}
            <div className="p-4 border-b border-slate-200">
                <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
                    Session
                </h2>

                {/* API Status */}
                <div className="flex items-center gap-2 mb-3">
                    <div
                        className={`w-2 h-2 rounded-full ${apiHealthy ? 'bg-green-500' : 'bg-red-500'
                            }`}
                    />
                    <span className="text-sm text-slate-600">
                        API: {apiHealthy ? 'Connected' : 'Disconnected'}
                    </span>
                </div>

                {/* Current Session */}
                {session && (
                    <div className="bg-slate-50 rounded-lg p-3 mb-3">
                        <p className="text-xs text-slate-500">Current Session</p>
                        <p className="text-sm text-slate-700 truncate" title={currentSessionItem?.title || undefined}>
                            {currentSessionItem ? formatSessionLabel(currentSessionItem) : `${session.id.slice(0, 12)}...`}
                        </p>
                    </div>
                )}

                {/* New Session Button */}
                <button
                    onClick={handleNewSession}
                    disabled={!apiHealthy || isCreating}
                    className="w-full py-2 px-3 bg-teal-600 text-white text-sm font-medium rounded-lg
                     hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors duration-200"
                >
                    {isCreating ? 'Creating...' : '+ New Session'}
                </button>
            </div>

            {/* Session History */}
            <div className="flex-1 overflow-hidden flex flex-col">
                <div className="px-4 pt-4 pb-2">
                    <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                        History
                    </h2>
                </div>
                <div className="flex-1 overflow-y-auto px-2">
                    {visibleSessions.length === 0 ? (
                        <p className="text-xs text-slate-400 px-2 py-4 text-center">
                            No previous sessions
                        </p>
                    ) : (
                        <div className="space-y-1">
                            {visibleSessions.map((s) => (
                                <button
                                    key={s.session_id}
                                    onClick={() => handleSelectSession(s.session_id)}
                                    className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${session?.id === s.session_id
                                        ? 'bg-teal-50 text-teal-700 border border-teal-200'
                                        : 'hover:bg-slate-100 text-slate-600'
                                        }`}
                                >
                                    <p className="text-xs truncate" title={s.title || undefined}>
                                        {formatSessionLabel(s)}
                                    </p>
                                    <p className="text-xs text-slate-400 mt-0.5">
                                        {formatDate(s.created_at)}
                                    </p>
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* Footer with Voice Settings */}
            <div className="border-t border-slate-200">
                <div className="p-2">
                    {/* Voice settings moved to RightSidebar */}
                </div>
                <p className="text-xs text-slate-400 text-center pb-3">
                    VideoAgent Studio v0.1
                </p>
            </div>
        </aside>
    );
}
