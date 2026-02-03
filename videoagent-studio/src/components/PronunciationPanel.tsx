'use client';

import React, { useState, useEffect } from 'react';
import RecordRTC from 'recordrtc';
import { api } from '@/lib/api';
import { Pronunciation } from '@/lib/types';
import { useSessionStore } from '@/store/session';

interface PronunciationPanelProps {
    sessionId?: string | null;
}

export function PronunciationPanel({ sessionId }: PronunciationPanelProps) {
    const [pronunciations, setPronunciations] = useState<Pronunciation[]>([]);
    const [loading, setLoading] = useState(true);
    const [isAdding, setIsAdding] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isRecording, setIsRecording] = useState(false);
    const mediaRecorderRef = React.useRef<any | null>(null);
    const audioChunksRef = React.useRef<Blob[]>([]);

    const [isGenerating, setIsGenerating] = useState(false);

    // Form state
    const [word, setWord] = useState('');
    const [phonetic, setPhonetic] = useState('');
    const [alwaysIncluded, setAlwaysIncluded] = useState(false);

    const [englishSpelling, setEnglishSpelling] = useState('');

    useEffect(() => {
        loadPronunciations();
    }, [sessionId]);

    const loadPronunciations = async () => {
        if (!sessionId) return;
        setLoading(true);
        try {
            const list = await api.listPronunciations(sessionId);
            setPronunciations(list);
        } catch (err) {
            console.error('Failed to load pronunciations:', err);
        } finally {
            setLoading(false);
        }
    };

    const handleAdd = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        if (!word || !phonetic) return;

        try {
            await api.createPronunciation({
                word,
                phonetic_spelling: phonetic, // Saving IPA as the canonical representation
                session_id: alwaysIncluded ? undefined : (sessionId || undefined),
                always_included: alwaysIncluded
            });
            // Reset form
            setWord('');
            setPhonetic('');
            setEnglishSpelling('');
            setAlwaysIncluded(false);
            setIsAdding(false);
            // Reload list
            loadPronunciations();
        } catch (err: any) {
            setError(err.message || 'Failed to add pronunciation');
        }
    };

    const handleDelete = async (id: string) => {
        try {
            await api.deletePronunciation(id);
            loadPronunciations();
        } catch (err) {
            console.error('Failed to delete pronunciation:', err);
        }
    };

    const toggleRecording = async () => {
        if (isGenerating) return;
        setError(null); // Clear previous errors

        if (isRecording) {
            // Stop recording
            if (mediaRecorderRef.current) {
                mediaRecorderRef.current.stopRecording(() => {
                    const blob = mediaRecorderRef.current!.getBlob();

                    // Stop all tracks to release microphone
                    if (mediaRecorderRef.current) {
                        // Ensure tracks are stopped
                    }

                    setIsRecording(false);
                    handleGeneration(blob);
                });
            }
        } else {
            // Start recording
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const recorder = new RecordRTC(stream, {
                    type: 'audio',
                    mimeType: 'audio/wav',
                    recorderType: RecordRTC.StereoAudioRecorder,
                    numberOfAudioChannels: 1
                });

                mediaRecorderRef.current = recorder;
                recorder.startRecording();
                setIsRecording(true);

                (mediaRecorderRef.current as any).stream = stream;

            } catch (err) {
                console.error('Error accessing microphone:', err);
                setError('Could not access microphone. Please ensure permissions are granted.');
            }
        }
    };

    const handleGeneration = async (blob: Blob) => {
        if (mediaRecorderRef.current && (mediaRecorderRef.current as any).stream) {
            (mediaRecorderRef.current as any).stream.getTracks().forEach((track: MediaStreamTrack) => track.stop());
        }

        setIsGenerating(true);
        setError(null);
        try {
            // Generate unique filename
            const filename = `audio_${Date.now()}.wav`;
            const result = await api.generatePronunciation(blob, filename);
            setPhonetic(result.phonetic_spelling);
            setEnglishSpelling(result.english_spelling);
        } catch (err) {
            console.error('Failed to generate pronunciation:', err);
            setError('Failed to generate pronunciation. Please try again.');
        } finally {
            setIsGenerating(false);
        }
    };

    const sessionItems = pronunciations.filter(p => p.session_id === sessionId && !p.always_included && !p.is_company_default);
    const profileItems = pronunciations.filter(p => p.always_included && !p.is_company_default);
    const companyItems = pronunciations.filter(p => p.is_company_default);

    if (loading) {
        return <div className="p-4 text-center text-slate-400 animate-pulse">Loading pronunciations...</div>;
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <p className="text-xs text-slate-400">
                    Control how specific names or terms are pronounced.
                </p>
                <button
                    onClick={() => setIsAdding(!isAdding)}
                    className={`p-1.5 rounded-lg transition-colors ${isAdding ? 'bg-slate-200 text-slate-600' : 'bg-teal-600 text-white hover:bg-teal-700'}`}
                >
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                    </svg>
                </button>
            </div>

            {isAdding && (
                <div className="bg-slate-50 p-4 rounded-xl border border-slate-100 space-y-4">
                    <div className="space-y-1">
                        <label className="text-xs font-medium text-slate-500 uppercase tracking-wider">Step 1: The Word</label>
                        <input
                            type="text"
                            value={word}
                            onChange={(e) => setWord(e.target.value)}
                            placeholder="e.g. Amine Kammah"
                            className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg focus:ring-2 focus:ring-teal-500/20 focus:border-teal-500 outline-none"
                            autoFocus
                        />
                    </div>

                    <div className="space-y-3">
                        <label className="text-xs font-medium text-slate-500 uppercase tracking-wider flex items-center gap-2">
                            Step 2: How is it pronounced?
                        </label>

                        <div className="space-y-2">
                            <button
                                type="button"
                                onClick={toggleRecording}
                                disabled={isGenerating}
                                className={`w-full py-3 rounded-xl border-2 flex flex-col items-center justify-center gap-2 transition-all ${isRecording
                                    ? 'bg-red-50 border-red-200 text-red-500 animate-pulse'
                                    : isGenerating
                                        ? 'bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed'
                                        : 'bg-white border-dashed border-teal-200 text-teal-600 hover:border-teal-400 hover:bg-teal-50'
                                    }`}
                            >
                                <div className={`p-2 rounded-full ${isRecording ? 'bg-red-100' : isGenerating ? 'bg-slate-100' : 'bg-teal-100'}`}>
                                    {isGenerating ? (
                                        <svg className="animate-spin w-5 h-5 text-slate-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                        </svg>
                                    ) : (
                                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-5 h-5">
                                            <path strokeLinecap="round" strokeLinejoin="round" d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
                                        </svg>
                                    )}
                                </div>
                                <div className="text-center">
                                    <span className="text-sm font-bold block">
                                        {isRecording ? 'Listening...' : isGenerating ? 'Generating...' : 'Record & Generate'}
                                    </span>
                                </div>
                            </button>

                            {(phonetic || englishSpelling) && (
                                <div className="p-3 bg-slate-100 rounded-lg border border-slate-200 space-y-2">
                                    <div className="flex items-start gap-3">
                                        <div className="flex-1 space-y-1">
                                            <span className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">IPA Spelling</span>
                                            <div className="text-sm font-mono text-slate-700 bg-white px-2 py-1 rounded border border-slate-100">{phonetic}</div>
                                        </div>
                                        <div className="flex-1 space-y-1">
                                            <span className="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">English-like</span>
                                            <div className="text-sm font-medium text-slate-700 bg-white px-2 py-1 rounded border border-slate-100">{englishSpelling}</div>
                                        </div>
                                    </div>
                                    <p className="text-[10px] text-center text-slate-400 italic pt-1">
                                        Record again if this doesn't look right.
                                    </p>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="flex items-center gap-2 pt-1">
                        <input
                            type="checkbox"
                            tabIndex={0}
                            id="alwaysIncluded"
                            checked={alwaysIncluded}
                            onChange={(e) => setAlwaysIncluded(e.target.checked)}
                            className="w-3.5 h-3.5 text-teal-600 border-slate-300 rounded focus:ring-teal-500"
                        />
                        <label htmlFor="alwaysIncluded" className="text-xs text-slate-600 cursor-pointer select-none group relative">
                            Save as User Default (all videos)
                            <div className="absolute left-0 bottom-full mb-2 w-48 p-2 bg-slate-900 text-white text-[11px] rounded shadow-xl opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                                This pronunciation will be applied across all your future videos.
                            </div>
                        </label>
                    </div>

                    {error && <p className="text-[10px] text-red-500">{error}</p>}

                    <form onSubmit={handleAdd} className="flex gap-2 pt-2">
                        <button
                            type="submit"
                            className="flex-1 bg-teal-600 text-white py-2 rounded-lg text-xs font-semibold hover:bg-teal-700 transition-colors"
                        >
                            Save Guidance
                        </button>
                        <button
                            type="button"
                            onClick={() => setIsAdding(false)}
                            className="px-3 py-2 text-slate-400 hover:text-slate-600 text-xs"
                        >
                            Cancel
                        </button>
                    </form>
                </div>
            )}

            <div className="space-y-6">
                {/* Session Specific */}
                <div className="space-y-3">
                    <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider flex items-center gap-2">
                        This Session
                        <span className="h-px flex-1 bg-slate-100"></span>
                    </h3>
                    {sessionItems.length === 0 ? (
                        <p className="text-xs text-slate-400 italic px-1">No session-specific guidance.</p>
                    ) : (
                        <div className="space-y-2">
                            {sessionItems.map(item => (
                                <PronunciationItem key={item.id} item={item} onDelete={() => handleDelete(item.id)} />
                            ))}
                        </div>
                    )}
                </div>

                {/* Profile Defaults - "Always Included" */}
                <div className="space-y-3">
                    <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider flex items-center gap-2 group relative">
                        User Defaults
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3 h-3 text-slate-300">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
                        </svg>
                        <div className="absolute left-0 bottom-full mb-1 w-48 p-2 bg-slate-900 text-white text-[11px] font-normal normal-case rounded shadow-xl opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                            These pronunciations are automatically applied to all your videos.
                        </div>
                        <span className="h-px flex-1 bg-slate-100"></span>
                    </h3>
                    {profileItems.length === 0 ? (
                        <p className="text-xs text-slate-400 italic px-1">No custom defaults set.</p>
                    ) : (
                        <div className="space-y-2">
                            {profileItems.map(item => (
                                <PronunciationItem key={item.id} item={item} onDelete={() => handleDelete(item.id)} />
                            ))}
                        </div>
                    )}
                </div>

                {/* Company Defaults */}
                {companyItems.length > 0 && (
                    <div className="space-y-3">
                        <h3 className="text-xs font-medium text-slate-500 uppercase tracking-wider flex items-center gap-2 cursor-help group relative">
                            Company Defaults
                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3 h-3 text-slate-300">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
                            </svg>
                            <div className="absolute left-0 bottom-full mb-1 w-48 p-2 bg-slate-900 text-white text-[11px] font-normal normal-case rounded shadow-xl opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10">
                                Mandatory pronunciations set by your organization.
                            </div>
                            <span className="h-px flex-1 bg-slate-100"></span>
                        </h3>
                        <div className="space-y-2 opacity-70">
                            {companyItems.map(item => (
                                <PronunciationItem key={item.id} item={item} readOnly />
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

function PronunciationItem({ item, onDelete, readOnly }: { item: Pronunciation; onDelete?: () => void, readOnly?: boolean }) {
    return (
        <div className="flex items-center justify-between p-2 bg-white border border-slate-100 rounded-lg group hover:border-teal-500/30 transition-all">
            <div className="min-w-0 pr-2">
                <div className="text-sm font-medium text-slate-700 truncate">{item.word}</div>
                <div className="text-xs text-slate-400 italic">[{item.phonetic_spelling}]</div>
            </div>
            {!readOnly && (
                <button
                    onClick={onDelete}
                    className="opacity-0 group-hover:opacity-100 p-1 text-slate-300 hover:text-red-500 transition-all"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3.5 h-3.5">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            )}
        </div>
    );
}
