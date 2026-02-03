'use client';

import { useEffect, useState } from 'react';
import { useSessionStore } from '@/store/session';
import { useSearchParams, useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { SessionListItem } from '@/lib/types';


export function Sidebar() {
    const session = useSessionStore(state => state.session);
    const user = useSessionStore(state => state.user);
    const apiHealthy = useSessionStore(state => state.apiHealthy);
    const createSession = useSessionStore(state => state.createSession);
    const loadSession = useSessionStore(state => state.loadSession);


    const [sessionInput, setSessionInput] = useState('');
    const [isCreating, setIsCreating] = useState(false);
    const [isCollapsed, setIsCollapsed] = useState(true);
    const [sessions, setSessions] = useState<SessionListItem[]>([]);

    const searchParams = useSearchParams();
    const router = useRouter();

    // Check API health on mount


    // Fetch sessions when API becomes healthy or user changes
    useEffect(() => {
        if (apiHealthy && user) {
            fetchSessions();
        } else {
            setSessions([]);
        }
    }, [apiHealthy, user]);

    const fetchSessions = async () => {
        try {
            const response = await api.listSessions();
            setSessions(response.sessions);
        } catch (error) {
            console.error('Failed to fetch sessions:', error);
        }
    };

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
    }, [apiHealthy, searchParams, session]); // Check when these change

    // Auto-create session if API is healthy and no session exists AND no session in URL
    useEffect(() => {
        const sessionIdParam = searchParams.get('sessionId');
        if (apiHealthy && !session && !isCreating && !sessionIdParam) {
            handleNewSession();
        }
    }, [apiHealthy, session, searchParams]);

    const handleNewSession = async () => {
        setIsCreating(true);
        try {
            const newSessionId = await createSession();
            router.push(`/?sessionId=${newSessionId}`);
        } catch (error) {
            setIsCreating(false);
        }
    };

    const handleLoadSession = () => {
        if (sessionInput.trim()) {
            loadSession(sessionInput.trim());
            setSessionInput('');
        }
    };

    const handleSelectSession = (sessionId: string) => {
        loadSession(sessionId);
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
                        <p className="text-sm font-mono text-slate-700 truncate">
                            {session.id.slice(0, 12)}...
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
                    {sessions.length === 0 ? (
                        <p className="text-xs text-slate-400 px-2 py-4 text-center">
                            No previous sessions
                        </p>
                    ) : (
                        <div className="space-y-1">
                            {sessions.map((s) => (
                                <button
                                    key={s.session_id}
                                    onClick={() => handleSelectSession(s.session_id)}
                                    className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${session?.id === s.session_id
                                        ? 'bg-teal-50 text-teal-700 border border-teal-200'
                                        : 'hover:bg-slate-100 text-slate-600'
                                        }`}
                                >
                                    <p className="font-mono text-xs truncate">
                                        {s.session_id.slice(0, 12)}...
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
