'use client';

import { useState } from 'react';
import { useSessionStore } from '@/store/session';
import { VoiceSettings } from './VoiceSettings';
import { PronunciationPanel } from './PronunciationPanel';

export function RightSidebar() {
    const [isExpanded, setIsExpanded] = useState(false);
    const [activeTab, setActiveTab] = useState<'voice' | 'pronunciations'>('voice');
    const user = useSessionStore(state => state.user);
    const session = useSessionStore(state => state.session);
    const isProcessing = useSessionStore(state => state.isProcessing);

    return (
        <aside
            className={`fixed right-0 top-16 bottom-0 z-50 bg-white border-l border-slate-200 transition-all duration-300 shadow-lg flex flex-col ${isExpanded ? 'w-80' : 'w-10'
                }`}
        >
            {/* Toggle/Icon Area */}
            <div className="flex flex-col items-center pt-4 gap-4 bg-slate-50 h-full">
                <button
                    onClick={() => {
                        if (isExpanded && activeTab === 'voice') {
                            setIsExpanded(false);
                        } else {
                            setIsExpanded(true);
                            setActiveTab('voice');
                        }
                    }}
                    className={`p-2 rounded-xl transition-all duration-200 group relative ${isExpanded && activeTab === 'voice' ? 'bg-teal-50 text-teal-600' : 'hover:bg-teal-50 text-slate-400 hover:text-teal-600'
                        }`}
                    title="Voice Settings"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
                    </svg>

                    {/* Tooltip for collapsed state */}
                    {!isExpanded && (
                        <div className="absolute right-full mr-2 top-1/2 -translate-y-1/2 px-2 py-1 bg-slate-800 text-white text-xs rounded opacity-0 group-hover:opacity-100 whitespace-nowrap pointer-events-none">
                            Voice Settings
                        </div>
                    )}
                </button>

                <button
                    onClick={() => {
                        if (isExpanded && activeTab === 'pronunciations') {
                            setIsExpanded(false);
                        } else {
                            setIsExpanded(true);
                            setActiveTab('pronunciations');
                        }
                    }}
                    className={`p-2 rounded-xl transition-all duration-200 group relative ${isExpanded && activeTab === 'pronunciations' ? 'bg-teal-50 text-teal-600' : 'hover:bg-teal-50 text-slate-400 hover:text-teal-600'
                        }`}
                    title="Pronunciations"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M12 18.75V16.5m0-4.5V9m3 3H9m1.5-12H22.5A2.25 2.25 0 0124 2.25v2.25a2.25 2.25 0 01-2.25 2.25H10.5A2.25 2.25 0 018.25 4.5V2.25A2.25 2.25 0 0110.5 0zm-7.5 15H15a2.25 2.25 0 012.25 2.25v2.25A2.25 2.25 0 0115 21.75H3a2.25 2.25 0 01-2.25-2.25v-2.25A2.25 2.25 0 013 16.5z" />
                    </svg>

                    {/* Tooltip for collapsed state */}
                    {!isExpanded && (
                        <div className="absolute right-full mr-2 top-1/2 -translate-y-1/2 px-2 py-1 bg-slate-800 text-white text-xs rounded opacity-0 group-hover:opacity-100 whitespace-nowrap pointer-events-none">
                            Pronunciations
                        </div>
                    )}
                </button>
            </div>

            {/* Expanded Content Area - Overlays the slim bar's right side background if we want, or side-by-side? 
                Actually, the requirements said "expand".
                If I make the whole aside w-80, the content should assume the icon is on the left or top?
                Let's change layout: when expanded, we have the icon strip on the left, and content on right?
                Or just a simple drawer.
                
                Let's stick to:
                - Slim vertical strip on the right (always visible? or expands?)
                User said: "The bar should only have the icon. Once clicked, it should expand..."
                
                My implementation:
                Aside width changes.
                Inside:
                IF Expanded: Show full content.
                If I use w-80, I can put the content in a div.
            */}

            {isExpanded && (
                <div className="absolute inset-y-0 left-10 right-0 bg-white p-4 overflow-y-auto border-l border-slate-100">
                    <div className="flex items-center justify-between mb-6">
                        <h2 className="font-serif font-bold text-slate-800 text-lg">
                            {activeTab === 'voice' ? 'Voice Studio' : 'Pronunciations'}
                        </h2>
                        <button
                            onClick={() => setIsExpanded(false)}
                            className="p-1 hover:bg-slate-100 rounded text-slate-400"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                            </svg>
                        </button>
                    </div>

                    {activeTab === 'voice' ? (
                        <div className="space-y-6">
                            <div className="space-y-2">
                                <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                                    Voice Over
                                </label>
                                <div className="bg-slate-50 p-1 rounded-xl">
                                    <VoiceSettings
                                        userId={user?.id}
                                        currentVoice={user?.settings?.tts_voice}
                                        direction="down"
                                        onVoiceChange={(voiceId) => {
                                            const currentUser = useSessionStore.getState().user;
                                            if (currentUser) {
                                                useSessionStore.getState().setUser({
                                                    ...currentUser,
                                                    settings: { ...currentUser.settings, tts_voice: voiceId }
                                                });
                                            }
                                        }}
                                    />
                                </div>
                                <p className="text-xs text-slate-400">
                                    This voice will be used to generate voice-overs for your project.
                                </p>
                            </div>

                            <button
                                onClick={() => {
                                    useSessionStore.getState().sendMessage("Regenerate all voice overs");
                                    setIsExpanded(false);
                                }}
                                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-teal-50 text-teal-700 rounded-xl hover:bg-teal-100 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                                disabled={isProcessing}
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                                    <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 000 1.5h2.433l-2.433-2.43a.75.75 0 000-1.5v-4.24a.75.75 0 00-1.5 0v2.433l-.311-.311a7 7 0 00-11.712 3.138.75.75 0 001.449.39 5.5 5.5 0 019.201-2.466l.312.311h-2.433z" clipRule="evenodd" />
                                </svg>
                                Regenerate Voice Overs
                            </button>
                        </div>
                    ) : (
                        <PronunciationPanel sessionId={session?.id} />
                    )}
                </div>
            )}
        </aside>
    );
}
