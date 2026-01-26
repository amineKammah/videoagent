'use client';

import { useState } from 'react';
import { useSessionStore } from '@/store/session';

export function ProjectBrief() {
    const videoBrief = useSessionStore(state => state.videoBrief);
    const [isCollapsed, setIsCollapsed] = useState(false);

    if (!videoBrief) {
        return (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm mb-4 overflow-hidden">
                <div className="px-6 py-8 text-center">
                    <div className="mx-auto w-12 h-12 bg-slate-50 rounded-full flex items-center justify-center mb-3">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6 text-slate-400">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                        </svg>
                    </div>
                    <h3 className="text-slate-900 font-medium mb-1">No Brief Yet</h3>
                    <p className="text-slate-500 text-sm">
                        Chat with the agent to generate a video brief and storyboard.
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm shrink-0 overflow-hidden">
            {/* Header */}
            <button
                onClick={() => setIsCollapsed(!isCollapsed)}
                className="w-full px-4 py-2 flex items-center justify-between bg-slate-50 border-b border-slate-200 hover:bg-slate-100 transition-colors text-left"
            >
                <div>
                    <h3 className="font-semibold text-slate-800">Video Brief</h3>
                    <p className="text-xs text-slate-500">Campaign strategy and key messaging</p>
                </div>
                <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    className={`w-5 h-5 text-slate-400 transition-transform ${isCollapsed ? '' : 'rotate-180'}`}
                >
                    <path
                        fillRule="evenodd"
                        d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                        clipRule="evenodd"
                    />
                </svg>
            </button>

            {/* Content */}
            {!isCollapsed && (
                <div className="p-6 space-y-6">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
                                Objective
                            </p>
                            <p className="text-sm text-slate-700 leading-relaxed">
                                {videoBrief.video_objective}
                            </p>
                        </div>

                        <div>
                            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
                                Persona
                            </p>
                            <p className="text-sm text-slate-700 leading-relaxed">
                                {videoBrief.persona}
                            </p>
                        </div>
                    </div>

                    <div>
                        <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
                            Core Messages
                        </p>
                        <ul className="space-y-2">
                            {videoBrief.key_messages.slice(0, 3).map((msg, idx) => (
                                <li key={idx} className="flex gap-2 text-sm text-slate-700 leading-relaxed">
                                    <span className="text-slate-400 select-none">•</span>
                                    <span>{msg}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
            )}
        </div>
    );
}
