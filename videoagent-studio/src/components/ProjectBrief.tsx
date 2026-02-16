'use client';

import { useState, useEffect } from 'react';
import { useSessionStore } from '@/store/session';
import { api } from '@/lib/api';
import { VideoBrief, Feedback } from '@/lib/types';
import { FeedbackControl } from './FeedbackControl';

export function ProjectBrief() {
    const { videoBrief, setVideoBrief, session, sendMessage } = useSessionStore();
    const [isCollapsed, setIsCollapsed] = useState(false);
    const [isEditing, setIsEditing] = useState(false);
    const [editForm, setEditForm] = useState<VideoBrief | null>(null);
    const [isSaving, setIsSaving] = useState(false);
    const [feedback, setFeedback] = useState<Feedback | null>(null);

    useEffect(() => {
        if (!session?.id) return;
        const loadFeedback = async () => {
            try {
                // Fetch feedback specifically for video_brief
                const list = await api.listFeedback(session.id, 'video_brief');
                if (list.length > 0) {
                    setFeedback(list[0]);
                } else {
                    setFeedback(null);
                }
            } catch (err) {
                console.error('Failed to load brief feedback:', err);
            }
        };
        loadFeedback();
    }, [session?.id]);

    const handleFeedbackUpdate = (updated: Feedback) => {
        setFeedback(updated);
    };

    useEffect(() => {
        if (isEditing && videoBrief) {
            setEditForm(JSON.parse(JSON.stringify(videoBrief)));
        }
    }, [isEditing, videoBrief]);

    const getBriefChanges = (original: VideoBrief, updated: VideoBrief): string[] => {
        const changes: string[] = [];
        if (original.video_objective !== updated.video_objective) {
            changes.push(`Changed objective from "${original.video_objective}" to "${updated.video_objective}"`);
        }
        if (original.persona !== updated.persona) {
            changes.push(`Changed persona from "${original.persona}" to "${updated.persona}"`);
        }
        if (JSON.stringify(original.key_messages) !== JSON.stringify(updated.key_messages)) {
            changes.push(`Updated key messages.`);
        }
        return changes;
    };

    const handleSave = async (notifyAgent: boolean = false) => {
        if (!session || !editForm || !videoBrief) return;
        setIsSaving(true);
        try {
            const updated = await api.updateVideoBrief(session.id, editForm);
            setVideoBrief(updated);

            // Close the edit mode immediately so the user can continue
            setIsEditing(false);

            if (notifyAgent) {
                const changes = getBriefChanges(videoBrief, editForm);
                if (changes.length > 0) {
                    const message = `I updated the Video Brief:\n- ${changes.join('\n- ')}`;
                    // Fire and forget, don't await the message sending
                    sendMessage(message).catch(err => console.error('Failed to notify agent:', err));
                }
            }
        } catch (error) {
            console.error('Failed to save brief:', error);
            // Optionally show error toast
        } finally {
            setIsSaving(false);
        }
    };

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
            <div className="w-full px-4 py-2 flex items-center justify-between bg-slate-50 border-b border-slate-200">
                <div className="flex items-center gap-2 cursor-pointer flex-1" onClick={() => setIsCollapsed(!isCollapsed)}>
                    <div>
                        <h3 className="font-semibold text-slate-800">Video Brief</h3>
                        <p className="text-xs text-slate-500">Campaign strategy and key messaging</p>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    {!isCollapsed && !isEditing && (
                        <button
                            onClick={() => setIsEditing(true)}
                            className="p-1.5 text-slate-500 hover:text-teal-600 hover:bg-white rounded-lg transition-colors"
                            title="Edit Brief"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                                <path d="M5.433 13.917l1.262-3.155A4 4 0 017.58 9.42l6.92-6.918a2.121 2.121 0 013 3l-6.92 6.918c-.383.383-.84.685-1.343.886l-3.154 1.262a.5.5 0 01-.65-.65z" />
                                <path d="M3.5 5.75c0-.69.56-1.25 1.25-1.25H10A.75.75 0 0010 3H4.75A2.75 2.75 0 002 5.75v9.5A2.75 2.75 0 004.75 18h9.5A2.75 2.75 0 0017 15.25V10a.75.75 0 00-1.5 0v5.25c0 .69-.56 1.25-1.25 1.25h-9.5c-.69 0-1.25-.56-1.25-1.25v-9.5z" />
                            </svg>
                        </button>
                    )}

                    <button
                        onClick={() => setIsCollapsed(!isCollapsed)}
                        className="p-1.5 text-slate-400 hover:bg-white rounded-lg transition-colors"
                    >
                        <svg
                            xmlns="http://www.w3.org/2000/svg"
                            viewBox="0 0 20 20"
                            fill="currentColor"
                            className={`w-5 h-5 transition-transform ${isCollapsed ? '' : 'rotate-180'}`}
                        >
                            <path
                                fillRule="evenodd"
                                d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                                clipRule="evenodd"
                            />
                        </svg>
                    </button>
                </div>
            </div>

            {/* Content */}
            {!isCollapsed && (
                <div className="relative p-6 pb-16 space-y-6">
                    {isEditing && editForm ? (
                        <div className="space-y-4">
                            <div>
                                <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">Objective</label>
                                <textarea
                                    className="w-full text-sm p-3 border border-slate-200 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none min-h-[80px]"
                                    value={editForm.video_objective}
                                    onChange={(e) => setEditForm({ ...editForm, video_objective: e.target.value })}
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">Persona</label>
                                <textarea
                                    className="w-full text-sm p-3 border border-slate-200 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none min-h-[60px]"
                                    value={editForm.persona}
                                    onChange={(e) => setEditForm({ ...editForm, persona: e.target.value })}
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">Core Messages (one per line)</label>
                                <textarea
                                    className="w-full text-sm p-3 border border-slate-200 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none min-h-[100px]"
                                    value={editForm.key_messages.join('\n')}
                                    onChange={(e) => setEditForm({ ...editForm, key_messages: e.target.value.split('\n').filter(line => line.trim() !== '') })}
                                />
                            </div>

                            <div className="flex gap-2 justify-end pt-2">
                                <button
                                    onClick={() => setIsEditing(false)}
                                    className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
                                    disabled={isSaving}
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={() => handleSave(false)}
                                    className="px-4 py-2 text-sm text-white bg-slate-600 hover:bg-slate-700 rounded-lg transition-colors shadow-sm disabled:opacity-50 flex items-center gap-2"
                                    disabled={isSaving}
                                >
                                    Save
                                </button>
                                <button
                                    onClick={() => handleSave(true)}
                                    className="px-4 py-2 text-sm text-white bg-teal-600 hover:bg-teal-700 rounded-lg transition-colors shadow-sm disabled:opacity-50 flex items-center gap-2"
                                    disabled={isSaving}
                                    title="Save changes and tell the agent about them"
                                >
                                    {isSaving && (
                                        <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                        </svg>
                                    )}
                                    Save & Notify Agent
                                </button>
                            </div>
                        </div>
                    ) : (
                        <>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                <div>
                                    <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
                                        Objective
                                    </p>
                                    <div className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
                                        {videoBrief.video_objective}
                                    </div>
                                </div>

                                <div>
                                    <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
                                        Persona
                                    </p>
                                    <div className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
                                        {videoBrief.persona}
                                    </div>
                                </div>
                            </div>

                            <div>
                                <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
                                    Core Messages
                                </p>
                                <ul className="space-y-2">
                                    {videoBrief.key_messages.map((msg, idx) => (
                                        <li key={idx} className="flex gap-2 text-sm text-slate-700 leading-relaxed">
                                            <span className="text-slate-400 select-none">•</span>
                                            <span>{msg}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        </>
                    )}



                    {/* Feedback Control - Sleek/Minimal */}
                    {!isEditing && session && (
                        <div className="absolute bottom-4 left-4">
                            <FeedbackControl
                                sessionId={session.id}
                                targetType="video_brief"
                                targetId={null}
                                initialFeedback={feedback}
                                onFeedbackUpdate={handleFeedbackUpdate}
                                variant="minimal"
                            />
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
