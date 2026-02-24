"use client";

import React, { useState, useEffect, useRef } from 'react';
import { api } from '@/lib/api';
import { VoiceOption } from '@/lib/types';
import VoiceCloneWizard from './VoiceCloneWizard';

interface VoiceSettingsProps {
    userId?: string;
    currentVoice?: string;
    onVoiceChange?: (voiceId: string) => void;
    direction?: 'up' | 'down';
}

export function VoiceSettings({ userId, currentVoice, onVoiceChange, direction = 'up' }: VoiceSettingsProps) {
    const [voices, setVoices] = useState<VoiceOption[]>([]);
    const [selectedVoice, setSelectedVoice] = useState<string>(currentVoice || 'Kore');
    const [playingVoice, setPlayingVoice] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [isOpen, setIsOpen] = useState(false);
    const [isCloneModalOpen, setIsCloneModalOpen] = useState(false);
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        loadVoices();
    }, []);

    useEffect(() => {
        if (currentVoice) {
            setSelectedVoice(currentVoice);
        }
    }, [currentVoice]);

    // Close dropdown on click outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Stop audio when dropdown closes
    useEffect(() => {
        if (!isOpen) {
            if (audioRef.current) {
                audioRef.current.pause();
            }
            setPlayingVoice(null);
        }
    }, [isOpen]);

    // Cleanup audio on unmount
    useEffect(() => {
        return () => {
            if (audioRef.current) {
                audioRef.current.pause();
            }
        };
    }, []);

    const loadVoices = async () => {
        try {
            const voiceList = await api.getVoices();
            setVoices(voiceList);
        } catch (error) {
            console.error('Failed to load voices:', error);
        } finally {
            setLoading(false);
        }
    };

    const playPreview = (voice: VoiceOption) => {
        if (audioRef.current) {
            audioRef.current.pause();
        }

        if (playingVoice === voice.id) {
            setPlayingVoice(null);
            return;
        }

        const audio = new Audio(voice.sample_url);
        audioRef.current = audio;
        setPlayingVoice(voice.id);

        audio.onended = () => setPlayingVoice(null);
        audio.onerror = () => setPlayingVoice(null);
        audio.play().catch(() => setPlayingVoice(null));
    };

    const handleSelect = async (voiceId: string) => {
        setSelectedVoice(voiceId);
        setIsOpen(false);

        if (userId) {
            setSaving(true);
            try {
                // Update DB persistence
                await api.updateUserSettings(userId, { tts_voice: voiceId });
                onVoiceChange?.(voiceId);
            } catch (error) {
                console.error('Failed to save voice preference:', error);
            } finally {
                setSaving(false);
            }
        } else {
            onVoiceChange?.(voiceId);
        }
    };

    const handleDeleteVoice = async (e: React.MouseEvent, voice: VoiceOption) => {
        e.stopPropagation();
        if (!voice.db_id) return;

        try {
            if (playingVoice === voice.id) {
                audioRef.current?.pause();
                setPlayingVoice(null);
            }
            await api.deleteClonedVoice(voice.db_id);
            setVoices(voices.filter(v => v.id !== voice.id));
            if (selectedVoice === voice.id) {
                // If the deleted voice was selected, revert to default
                const defaultVoice = voices.find(v => v.id !== voice.id)?.id || '';
                handleSelect(defaultVoice);
            }
        } catch (err) {
            console.error('Failed to delete voice:', err);
        }
    };

    const handleVoiceCloned = () => {
        loadVoices();
    };

    const selectedVoiceData = voices.find(v => v.id === selectedVoice);

    if (loading) {
        return (
            <div className="flex items-center gap-2 px-3 py-2 text-sm text-slate-400">
                <span className="animate-pulse">Loading voices...</span>
            </div>
        );
    }

    return (
        <div className="relative" ref={containerRef}>
            {/* Trigger Button */}
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="flex items-center gap-2 w-full px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
            >
                <svg
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={1.5}
                    stroke="currentColor"
                    className="w-4 h-4 text-slate-400"
                >
                    <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z"
                    />
                </svg>
                <span className="flex-1 text-left truncate">
                    Voice: {selectedVoiceData?.name || selectedVoice}
                </span>
                {saving && (
                    <span className="text-xs text-slate-400">Saving...</span>
                )}
                <svg
                    xmlns="http://www.w3.org/2000/svg"
                    fill="none"
                    viewBox="0 0 24 24"
                    strokeWidth={2}
                    stroke="currentColor"
                    className={`w-3 h-3 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
                >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
            </button>

            {/* Dropdown */}
            {isOpen && (
                <div className={`absolute left-0 right-0 bg-white border border-slate-200 rounded-lg shadow-xl max-h-72 overflow-y-auto z-50 ${direction === 'up'
                    ? 'bottom-full mb-1'
                    : 'top-full mt-1'
                    }`}>
                    <div className="p-2 border-b border-slate-100 sticky top-0 bg-white">
                        <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">
                            Select Voice
                        </span>
                    </div>
                    <div className="p-1">
                        <button
                            onClick={() => {
                                setIsOpen(false);
                                setIsCloneModalOpen(true);
                            }}
                            className="flex items-center gap-2 w-full px-2 py-2 mb-1 text-sm font-medium text-teal-600 hover:bg-teal-50 rounded-md transition-colors"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                            </svg>
                            Clone a Voice
                        </button>

                        {voices.some(v => v.category === 'cloned') && (
                            <>
                                <div className="px-2 py-1 mt-2 mb-1 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                                    Your Voices
                                </div>
                                {voices.filter(v => v.category === 'cloned').map((voice) => (
                                    <div
                                        key={voice.id}
                                        className={`flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors group ${selectedVoice === voice.id
                                            ? 'bg-teal-50 text-teal-700'
                                            : 'hover:bg-slate-50 text-slate-600'
                                            }`}
                                        onClick={() => handleSelect(voice.id)}
                                    >
                                        {/* Play button */}
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                playPreview(voice);
                                            }}
                                            className={`p-1.5 rounded-full hover:bg-slate-200 transition-colors ${playingVoice === voice.id ? 'text-teal-600 bg-teal-50' : 'text-slate-400'
                                                }`}
                                            title="Preview voice"
                                        >
                                            {playingVoice === voice.id ? (
                                                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3.5 h-3.5">
                                                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25v13.5m-7.5-13.5v13.5" />
                                                </svg>
                                            ) : (
                                                <svg xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 24 24" className="w-3.5 h-3.5">
                                                    <path d="M8 5.14v14l11-7-11-7z" />
                                                </svg>
                                            )}
                                        </button>

                                        {/* Voice info */}
                                        <div className="flex-1 min-w-0">
                                            <div className="text-sm font-medium truncate flex items-center gap-2">
                                                {voice.name}
                                                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-indigo-100 text-indigo-800">
                                                    Cloned
                                                </span>
                                            </div>
                                        </div>

                                        {/* Delete button (only for cloned voices with db_id) */}
                                        {voice.db_id && (
                                            <button
                                                onClick={(e) => handleDeleteVoice(e, voice)}
                                                className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100"
                                                title="Delete voice"
                                            >
                                                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                                                    <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                                                </svg>
                                            </button>
                                        )}

                                        {/* Selected indicator */}
                                        {selectedVoice === voice.id && (
                                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4 text-teal-600">
                                                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                                            </svg>
                                        )}
                                    </div>
                                ))}
                            </>
                        )}

                        <div className="px-2 py-1 mt-2 mb-1 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                            Premade Voices
                        </div>
                        {voices.filter(v => v.category !== 'cloned').map((voice) => (
                            <div
                                key={voice.id}
                                className={`flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors ${selectedVoice === voice.id
                                    ? 'bg-teal-50 text-teal-700'
                                    : 'hover:bg-slate-50 text-slate-600'
                                    }`}
                                onClick={() => handleSelect(voice.id)}
                            >
                                {/* Play button */}
                                <button
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        playPreview(voice);
                                    }}
                                    className={`p-1.5 rounded-full hover:bg-slate-200 transition-colors ${playingVoice === voice.id ? 'text-teal-600 bg-teal-50' : 'text-slate-400'
                                        }`}
                                    title="Preview voice"
                                >
                                    {playingVoice === voice.id ? (
                                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3.5 h-3.5">
                                            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25v13.5m-7.5-13.5v13.5" />
                                        </svg>
                                    ) : (
                                        <svg xmlns="http://www.w3.org/2000/svg" fill="currentColor" viewBox="0 0 24 24" className="w-3.5 h-3.5">
                                            <path d="M8 5.14v14l11-7-11-7z" />
                                        </svg>
                                    )}
                                </button>

                                {/* Voice info */}
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm font-medium truncate">{voice.name}</div>
                                    <div className="text-xs text-slate-400">{voice.gender}</div>
                                </div>

                                {/* Selected indicator */}
                                {selectedVoice === voice.id && (
                                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4 text-teal-600">
                                        <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                                    </svg>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Voice Clone Wizard Modal */}
            <VoiceCloneWizard
                isOpen={isCloneModalOpen}
                onClose={() => setIsCloneModalOpen(false)}
                onSuccess={handleVoiceCloned}
            />
        </div>
    );
}
