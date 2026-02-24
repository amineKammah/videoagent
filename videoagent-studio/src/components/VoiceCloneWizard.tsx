"use client";

import React, { useState, useRef, useEffect } from 'react';
import { api } from '@/lib/api';

interface VoiceCloneWizardProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

export default function VoiceCloneWizard({ isOpen, onClose, onSuccess }: VoiceCloneWizardProps) {
    const [step, setStep] = useState<1 | 2 | 3 | 4>(1);
    const [voiceName, setVoiceName] = useState('');
    const [voiceDescription, setVoiceDescription] = useState('');
    const [audioFile, setAudioFile] = useState<File | null>(null);
    const [isRecording, setIsRecording] = useState(false);
    const [recordingTime, setRecordingTime] = useState(0);
    const [isProcessing, setIsProcessing] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const audioChunksRef = useRef<Blob[]>([]);
    const timerRef = useRef<NodeJS.Timeout | null>(null);

    useEffect(() => {
        if (!isOpen) {
            // Reset state when closed
            setStep(1);
            setVoiceName('');
            setVoiceDescription('');
            setAudioFile(null);
            setIsRecording(false);
            setRecordingTime(0);
            setIsProcessing(false);
            setError(null);
            if (timerRef.current) clearInterval(timerRef.current);
            if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
                mediaRecorderRef.current.stop();
            }
        }
    }, [isOpen]);

    // Handle timer for recording
    useEffect(() => {
        if (isRecording) {
            timerRef.current = setInterval(() => {
                setRecordingTime((prev) => prev + 1);
            }, 1000);
        } else if (timerRef.current) {
            clearInterval(timerRef.current);
        }
        return () => {
            if (timerRef.current) clearInterval(timerRef.current);
        };
    }, [isRecording]);

    if (!isOpen) return null;

    const startRecording = async () => {
        try {
            setError(null);
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mediaRecorder = new MediaRecorder(stream);
            mediaRecorderRef.current = mediaRecorder;
            audioChunksRef.current = [];

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunksRef.current.push(event.data);
                }
            };

            mediaRecorder.onstop = () => {
                const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
                const file = new File([audioBlob], 'recorded_voice.wav', { type: 'audio/wav' });
                setAudioFile(file);

                // Stop all tracks to release microphone
                stream.getTracks().forEach(track => track.stop());
            };

            mediaRecorder.start();
            setIsRecording(true);
            setRecordingTime(0);
        } catch (err) {
            console.error('Error accessing microphone:', err);
            setError('Could not access microphone. Please ensure permissions are granted or upload an audio file instead.');
        }
    };

    const stopRecording = () => {
        if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
            mediaRecorderRef.current.stop();
            setIsRecording(false);
        }
    };

    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            setAudioFile(file);
        }
    };

    const formatTime = (seconds: number) => {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    };

    const handleClone = async () => {
        if (!audioFile || !voiceName.trim()) {
            setError('Please provide a name and audio file/recording.');
            return;
        }

        setIsProcessing(true);
        setError(null);
        setStep(4); // Move to processing step

        try {
            await api.cloneVoice(voiceName, [audioFile], voiceDescription);
            onSuccess(); // Triggers reload of voices list
            setTimeout(() => {
                onClose();
            }, 2000); // Give user a moment to see success state
        } catch (err: any) {
            console.error('Voice clone failed:', err);
            setError(err.message || 'Failed to clone voice. Please try again.');
            setStep(3); // Back to previous step to retry
        } finally {
            setIsProcessing(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm">
            <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">

                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-white sticky top-0">
                    <h2 className="text-xl font-bold text-slate-800">Clone Your Voice</h2>
                    <button
                        onClick={onClose}
                        className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-full transition-colors"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-5 h-5">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-6 bg-slate-50/50">

                    {/* Progress Indicator */}
                    <div className="flex items-center justify-center mb-8">
                        <div className="flex items-center gap-2">
                            {[1, 2, 3].map((s) => (
                                <React.Fragment key={s}>
                                    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-colors ${step === s ? 'bg-teal-600 text-white' :
                                        step > s ? 'bg-teal-100 text-teal-600' : 'bg-slate-200 text-slate-500'
                                        }`}>
                                        {step > s ? (
                                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                                                <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clipRule="evenodd" />
                                            </svg>
                                        ) : s}
                                    </div>
                                    {s < 3 && (
                                        <div className={`w-12 h-1 rounded-full ${step > s ? 'bg-teal-200' : 'bg-slate-200'}`} />
                                    )}
                                </React.Fragment>
                            ))}
                        </div>
                    </div>

                    {error && (
                        <div className="mb-6 p-4 bg-red-50 text-red-700 rounded-xl border border-red-100 text-sm flex items-start gap-3">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5 flex-shrink-0 mt-0.5">
                                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                            </svg>
                            <p>{error}</p>
                        </div>
                    )}

                    {/* Step 1: Welcome & Instructions */}
                    {step === 1 && (
                        <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                            <div className="text-center space-y-3 mb-8">
                                <div className="w-16 h-16 bg-gradient-to-br from-teal-400 to-emerald-500 rounded-2xl mx-auto flex items-center justify-center shadow-lg shadow-teal-500/20 mb-6">
                                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="white" className="w-8 h-8">
                                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
                                    </svg>
                                </div>
                                <h3 className="text-2xl font-bold text-slate-800">Create a Custom Voice</h3>
                                <p className="text-slate-600 max-w-md mx-auto">
                                    Clone your own voice to use for highly personalized video generation. The process takes less than a minute.
                                </p>
                            </div>

                            <div className="bg-white rounded-xl p-5 border border-slate-200 shadow-sm space-y-4">
                                <h4 className="font-semibold text-slate-800 flex items-center gap-2">
                                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5 text-amber-500">
                                        <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clipRule="evenodd" />
                                    </svg>
                                    Tips for the best result
                                </h4>
                                <ul className="space-y-3 text-sm text-slate-600">
                                    <li className="flex items-start gap-3">
                                        <div className="w-1.5 h-1.5 rounded-full bg-teal-500 mt-1.5 flex-shrink-0" />
                                        <p>Find a <strong>quiet environment</strong> without background noise.</p>
                                    </li>
                                    <li className="flex items-start gap-3">
                                        <div className="w-1.5 h-1.5 rounded-full bg-teal-500 mt-1.5 flex-shrink-0" />
                                        <p>Speak <strong>naturally and expressively</strong>, exactly how you'd sound in a video.</p>
                                    </li>
                                    <li className="flex items-start gap-3">
                                        <div className="w-1.5 h-1.5 rounded-full bg-teal-500 mt-1.5 flex-shrink-0" />
                                        <p>Provide <strong>at least 30 seconds</strong> of continuous audio.</p>
                                    </li>
                                </ul>
                            </div>
                        </div>
                    )}

                    {/* Step 2: Record or Upload */}
                    {step === 2 && (
                        <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">

                            <div className="bg-teal-50/50 rounded-xl p-5 border-l-4 border-teal-500 shadow-sm">
                                <h4 className="font-medium text-teal-800 mb-2 text-sm uppercase tracking-wider">Recommended text to read (Aim for &gt; 30 seconds):</h4>
                                <p className="text-slate-700 italic leading-relaxed font-serif mb-4">
                                    "It is as if every ray of sunshine tells its own story, a story of hope and new beginnings. As the rain tapped gently against the window, he sat there, wrapped in the warmth of an old knitted sweater. He watched as each drop made its own little journey along the pane, meandering and merging, before finally disappearing into the window sill. Isn't it wonderful how the world smells after a rain? Like being reborn! And there, a bird begins to sing as if to celebrate the rainbow."
                                </p>
                                <p className="text-slate-700 italic leading-relaxed font-serif">
                                    <strong>(Conversational)</strong> "Hey! It's been a while since we caught up. How have things been on your end? Let me know if you're free to grab a coffee sometime next week, I'd love to hear all about what you've been working on lately."
                                </p>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {/* Record Option */}
                                <div className={`relative flex flex-col items-center justify-center p-4 border-2 rounded-2xl transition-all ${isRecording
                                    ? 'border-red-400 bg-red-50/30'
                                    : audioFile && !isRecording && audioFile.name === 'recorded_voice.wav'
                                        ? 'border-teal-400 bg-teal-50/30'
                                        : 'border-slate-200 bg-white hover:border-slate-300'
                                    }`}>
                                    <h5 className="font-semibold text-slate-800 mb-4">Record Audio</h5>

                                    {isRecording ? (
                                        <div className="flex flex-col items-center space-y-4">
                                            <div className="w-20 h-20 bg-red-100 rounded-full flex items-center justify-center animate-pulse">
                                                <div className="w-12 h-12 bg-red-500 rounded-full" />
                                            </div>
                                            <div className="text-red-600 font-mono text-xl">{formatTime(recordingTime)}</div>
                                            <button
                                                onClick={stopRecording}
                                                className="mt-4 px-6 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg font-medium transition-colors"
                                            >
                                                Stop Recording
                                            </button>
                                        </div>
                                    ) : audioFile && audioFile.name === 'recorded_voice.wav' ? (
                                        <div className="flex flex-col items-center space-y-4 w-full">
                                            <div className="w-16 h-16 bg-teal-100 rounded-full flex items-center justify-center text-teal-600">
                                                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-8 h-8">
                                                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                                </svg>
                                            </div>
                                            <p className="text-teal-700 font-medium">Recording saved!</p>
                                            <audio src={URL.createObjectURL(audioFile)} controls className="w-full mt-2 h-10" />
                                            <button
                                                onClick={startRecording}
                                                className="mt-2 text-sm text-slate-500 hover:text-slate-800 transition-colors"
                                            >
                                                Record again
                                            </button>
                                        </div>
                                    ) : (
                                        <div className="flex flex-col items-center">
                                            <button
                                                onClick={startRecording}
                                                className="w-16 h-16 bg-teal-50 hover:bg-teal-100 text-teal-600 rounded-full flex items-center justify-center shadow-sm hover:shadow-md transition-all group"
                                            >
                                                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6 group-hover:scale-110 transition-transform">
                                                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
                                                </svg>
                                            </button>
                                            <p className="mt-3 text-sm text-slate-500 text-center">Click to start recording directly in your browser.<br /><span className="text-amber-600 font-medium">Please record for at least 30 seconds.</span></p>
                                        </div>
                                    )}
                                </div>

                                {/* Upload Option */}
                                <div className={`relative flex flex-col items-center justify-center p-4 border-2 border-dashed rounded-2xl transition-all ${audioFile && audioFile.name !== 'recorded_voice.wav'
                                    ? 'border-teal-400 bg-teal-50/30'
                                    : 'border-slate-300 bg-white hover:border-slate-400 hover:bg-slate-50/50'
                                    }`}>
                                    <h5 className="font-semibold text-slate-800 mb-4">Upload File</h5>

                                    {audioFile && audioFile.name !== 'recorded_voice.wav' ? (
                                        <div className="flex flex-col items-center space-y-4 w-full text-center">
                                            <div className="w-16 h-16 bg-teal-100 rounded-full flex items-center justify-center text-teal-600">
                                                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-8 h-8">
                                                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m3.75 9v6m3-3H9m1.5-12H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                                                </svg>
                                            </div>
                                            <p className="font-medium text-slate-800 truncate w-full px-4" title={audioFile.name}>
                                                {audioFile.name}
                                            </p>
                                            <audio src={URL.createObjectURL(audioFile)} controls className="w-full mt-2 h-10" />
                                            <label className="mt-2 text-sm text-slate-500 hover:text-slate-800 transition-colors cursor-pointer">
                                                Choose different file
                                                <input type="file" accept="audio/*" className="hidden" onChange={handleFileUpload} />
                                            </label>
                                        </div>
                                    ) : (
                                        <label className="flex flex-col items-center cursor-pointer w-full h-full justify-center">
                                            <div className="w-16 h-16 bg-slate-100 text-slate-500 rounded-full flex items-center justify-center shadow-sm hover:bg-slate-200 transition-all group mb-3">
                                                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6 group-hover:-translate-y-1 transition-transform">
                                                    <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                                                </svg>
                                            </div>
                                            <p className="text-sm text-slate-500 text-center">Upload .mp3, .wav, or .m4a<br />(Max 10MB)</p>
                                            <input type="file" accept="audio/*" className="hidden" onChange={handleFileUpload} />
                                        </label>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Step 3: Name & Options */}
                    {step === 3 && (
                        <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500 max-w-md mx-auto">
                            <div className="text-center mb-8">
                                <h3 className="text-2xl font-bold text-slate-800 mb-2">Name Your Voice</h3>
                                <p className="text-slate-600">Give your voice a distinctive name to easily find it later.</p>
                            </div>

                            <div className="space-y-5">
                                <div className="space-y-1.5">
                                    <label htmlFor="voiceName" className="block text-sm font-semibold text-slate-700">
                                        Voice Name <span className="text-red-500">*</span>
                                    </label>
                                    <input
                                        type="text"
                                        id="voiceName"
                                        value={voiceName}
                                        onChange={(e) => setVoiceName(e.target.value)}
                                        placeholder="e.g., Jane's Professional Voice"
                                        className="w-full px-4 py-3 bg-white border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-shadow"
                                        autoFocus
                                    />
                                </div>

                                <div className="space-y-1.5">
                                    <label htmlFor="voiceDescription" className="block text-sm font-semibold text-slate-700">
                                        Description <span className="text-slate-400 font-normal">(Optional)</span>
                                    </label>
                                    <textarea
                                        id="voiceDescription"
                                        value={voiceDescription}
                                        onChange={(e) => setVoiceDescription(e.target.value)}
                                        placeholder="e.g., Upbeat and energetic tone for product updates"
                                        rows={3}
                                        className="w-full px-4 py-3 bg-white border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-shadow resize-none"
                                    />
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Step 4: Processing / Success */}
                    {step === 4 && (
                        <div className="py-12 flex flex-col items-center justify-center animate-in zoom-in-95 duration-500">
                            {isProcessing ? (
                                <>
                                    <div className="relative w-24 h-24 mb-8">
                                        <div className="absolute inset-0 border-4 border-slate-100 rounded-full"></div>
                                        <div className="absolute inset-0 border-4 border-teal-500 rounded-full border-t-transparent animate-spin"></div>
                                        <div className="absolute inset-0 flex items-center justify-center">
                                            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-8 h-8 text-teal-600 animate-pulse">
                                                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
                                            </svg>
                                        </div>
                                    </div>
                                    <h3 className="text-xl font-bold text-slate-800 mb-2">Cloning Voice...</h3>
                                    <p className="text-slate-500 text-center max-w-sm">
                                        We are processing your audio and creating an AI model of your voice. This usually takes just a few seconds.
                                    </p>
                                </>
                            ) : error ? (
                                // This shouldn't typically render as we move back to step 3 on error, but just in case
                                <div className="text-center">
                                    <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-8 h-8 text-red-600">
                                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                                        </svg>
                                    </div>
                                    <h3 className="text-xl font-bold text-slate-800 mb-2">Cloning Failed</h3>
                                    <p className="text-slate-600 mb-6">{error}</p>
                                    <button
                                        onClick={() => setStep(3)}
                                        className="px-6 py-2.5 bg-slate-800 hover:bg-slate-700 text-white font-medium rounded-xl transition-colors"
                                    >
                                        Try Again
                                    </button>
                                </div>
                            ) : (
                                <div className="text-center animate-in zoom-in-50 duration-500 delay-150">
                                    <div className="w-20 h-20 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-6 shadow-lg shadow-green-500/20">
                                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={3} stroke="currentColor" className="w-10 h-10 text-green-600">
                                            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                                        </svg>
                                    </div>
                                    <h3 className="text-2xl font-bold text-slate-800 mb-2">Voice Successfully Cloned!</h3>
                                    <p className="text-slate-600 mb-6">
                                        <strong>{voiceName}</strong> is now available in your voice dropdown.
                                    </p>
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {/* Footer / Navigation */}
                {step < 4 && (
                    <div className="px-6 py-4 border-t border-slate-100 bg-slate-50 flex items-center justify-between sticky bottom-0">
                        {step > 1 ? (
                            <button
                                onClick={() => setStep(prev => (prev - 1) as any)}
                                className="px-5 py-2.5 text-slate-600 font-medium hover:bg-slate-200 rounded-xl transition-colors"
                            >
                                Back
                            </button>
                        ) : (
                            <div /> // Placeholder for simple layout
                        )}

                        <button
                            onClick={() => {
                                if (step === 1) setStep(2);
                                else if (step === 2) setStep(3);
                                else if (step === 3) handleClone();
                            }}
                            disabled={
                                (step === 2 && !audioFile) ||
                                (step === 3 && !voiceName.trim()) ||
                                isRecording
                            }
                            className={`px-8 py-2.5 rounded-xl font-medium transition-all shadow-sm flex items-center gap-2 ${((step === 2 && !audioFile) || (step === 3 && !voiceName.trim()) || isRecording)
                                ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                                : 'bg-teal-600 hover:bg-teal-700 text-white hover:shadow-md'
                                }`}
                        >
                            {step === 3 ? 'Clone Voice' : 'Continue'}
                            {step < 3 && (
                                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                                </svg>
                            )}
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
