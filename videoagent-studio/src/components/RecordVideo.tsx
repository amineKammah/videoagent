'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { api } from '@/lib/api';
import { UploadRecordingResponse } from '@/lib/types';

type RecordingMode = 'webcam' | 'screen' | 'both';
type RecordingState = 'idle' | 'preview' | 'countdown' | 'recording' | 'review' | 'uploading' | 'done';

interface RecordVideoProps {
    sessionId: string;
    sceneId: string;
    onComplete: (videoId: string, duration: number) => void;
    onCancel: () => void;
}

export function RecordVideo({ sessionId, sceneId, onComplete, onCancel }: RecordVideoProps) {
    const [mode, setMode] = useState<RecordingMode>('webcam');
    const [state, setState] = useState<RecordingState>('idle');
    const [countdown, setCountdown] = useState(3);
    const [elapsed, setElapsed] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [uploadProgress, setUploadProgress] = useState<string>('');
    const [recordedBlob, setRecordedBlob] = useState<Blob | null>(null);
    const [recordedUrl, setRecordedUrl] = useState<string | null>(null);

    const liveVideoRef = useRef<HTMLVideoElement>(null);
    const reviewVideoRef = useRef<HTMLVideoElement>(null);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const chunksRef = useRef<Blob[]>([]);
    const streamsRef = useRef<MediaStream[]>([]);
    const timerRef = useRef<NodeJS.Timeout | null>(null);
    const elapsedRef = useRef<NodeJS.Timeout | null>(null);
    const startRecordingRef = useRef<() => void>(() => { });
    const pendingStreamRef = useRef<MediaStream | null>(null);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            stopAllStreams();
            if (timerRef.current) clearInterval(timerRef.current);
            if (elapsedRef.current) clearInterval(elapsedRef.current);
            if (recordedUrl) URL.revokeObjectURL(recordedUrl);
        };
    }, [recordedUrl]);

    const stopAllStreams = useCallback(() => {
        streamsRef.current.forEach(stream => {
            stream.getTracks().forEach(track => track.stop());
        });
        streamsRef.current = [];
        pendingStreamRef.current = null;
        if (liveVideoRef.current) {
            liveVideoRef.current.srcObject = null;
        }
    }, []);

    // Attach the pending stream to the video element once it renders
    useEffect(() => {
        if (state === 'preview' && pendingStreamRef.current && liveVideoRef.current) {
            const video = liveVideoRef.current;
            video.srcObject = pendingStreamRef.current;
            video.muted = true;
            video.play().catch(err => {
                console.error('[RecordVideo] Failed to play preview:', err);
            });
            pendingStreamRef.current = null;
        }
    }, [state]);

    const startPreview = useCallback(async (selectedMode: RecordingMode) => {
        setError(null);
        stopAllStreams();

        try {
            let combinedStream: MediaStream;

            if (selectedMode === 'webcam') {
                const webcamStream = await navigator.mediaDevices.getUserMedia({
                    video: { width: { ideal: 1920 }, height: { ideal: 1080 }, facingMode: 'user' },
                    audio: true,
                });
                streamsRef.current = [webcamStream];
                combinedStream = webcamStream;
            } else if (selectedMode === 'screen') {
                const screenStream = await navigator.mediaDevices.getDisplayMedia({
                    video: { width: { ideal: 1920 }, height: { ideal: 1080 } },
                    audio: true,
                });
                streamsRef.current = [screenStream];
                combinedStream = screenStream;

                // Handle screen sharing stop (user clicks "Stop sharing" in the browser UI)
                screenStream.getVideoTracks()[0].onended = () => {
                    if (mediaRecorderRef.current?.state === 'recording') {
                        stopRecording();
                    } else {
                        stopAllStreams();
                        setState('idle');
                    }
                };
            } else {
                // Both: webcam + screen
                const [webcamStream, screenStream] = await Promise.all([
                    navigator.mediaDevices.getUserMedia({
                        video: { width: { ideal: 320 }, height: { ideal: 240 }, facingMode: 'user' },
                        audio: true,
                    }),
                    navigator.mediaDevices.getDisplayMedia({
                        video: { width: { ideal: 1920 }, height: { ideal: 1080 } },
                        audio: false,
                    }),
                ]);
                streamsRef.current = [webcamStream, screenStream];

                // Use screen as main, webcam audio
                const tracks = [
                    ...screenStream.getVideoTracks(),
                    ...webcamStream.getAudioTracks(),
                ];
                combinedStream = new MediaStream(tracks);

                screenStream.getVideoTracks()[0].onended = () => {
                    if (mediaRecorderRef.current?.state === 'recording') {
                        stopRecording();
                    } else {
                        stopAllStreams();
                        setState('idle');
                    }
                };
            }

            // Store stream in ref — the useEffect above will attach it after
            // the video element renders (state change triggers re-render)
            pendingStreamRef.current = combinedStream;
            setState('preview');
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : 'Failed to access camera/screen';
            if (message.includes('NotAllowed') || message.includes('Permission')) {
                setError('Permission denied. Please allow camera/screen access and try again.');
            } else {
                setError(message);
            }
        }
    }, [stopAllStreams]);

    const startCountdown = useCallback(() => {
        setCountdown(3);
        setState('countdown');
        let count = 3;

        timerRef.current = setInterval(() => {
            count -= 1;
            setCountdown(count);
            if (count <= 0) {
                if (timerRef.current) clearInterval(timerRef.current);
                console.log('[RecordVideo] Countdown done, calling startRecordingRef.current', typeof startRecordingRef.current);
                startRecordingRef.current();
            }
        }, 1000);
    }, []);

    const startRecording = useCallback(() => {
        console.log('[RecordVideo] startRecording called');
        const video = liveVideoRef.current;
        console.log('[RecordVideo] video element:', !!video, 'srcObject:', !!video?.srcObject);
        if (!video?.srcObject) {
            console.error('[RecordVideo] No video element or srcObject — cannot start recording');
            setState('preview'); // Go back to preview so user isn't stuck
            return;
        }

        const stream = video.srcObject as MediaStream;
        const activeTracks = stream.getTracks().filter(t => t.readyState === 'live');
        console.log('[RecordVideo] Stream tracks:', stream.getTracks().length, 'active:', activeTracks.length);

        if (activeTracks.length === 0) {
            console.error('[RecordVideo] All stream tracks are ended');
            setState('preview');
            return;
        }

        chunksRef.current = [];

        const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')
            ? 'video/webm;codecs=vp9,opus'
            : MediaRecorder.isTypeSupported('video/webm;codecs=vp8,opus')
                ? 'video/webm;codecs=vp8,opus'
                : 'video/webm';

        console.log('[RecordVideo] Using mimeType:', mimeType);

        try {
            const recorder = new MediaRecorder(stream, {
                mimeType,
                videoBitsPerSecond: 2_500_000,
            });

            recorder.ondataavailable = (e) => {
                if (e.data.size > 0) {
                    chunksRef.current.push(e.data);
                }
            };

            recorder.onstop = () => {
                const blob = new Blob(chunksRef.current, { type: mimeType });
                const url = URL.createObjectURL(blob);
                setRecordedBlob(blob);
                setRecordedUrl(url);
                stopAllStreams();
                setState('review');
            };

            recorder.onerror = (e) => {
                console.error('[RecordVideo] MediaRecorder error:', e);
            };

            recorder.start(1000); // chunk every second
            mediaRecorderRef.current = recorder;

            setElapsed(0);
            elapsedRef.current = setInterval(() => {
                setElapsed(prev => prev + 1);
            }, 1000);

            console.log('[RecordVideo] Recording started successfully');
            setState('recording');
        } catch (err) {
            console.error('[RecordVideo] Failed to create/start MediaRecorder:', err);
            setState('preview');
        }
    }, [stopAllStreams]);

    // Keep ref in sync so startCountdown interval always calls the latest version
    startRecordingRef.current = startRecording;

    const stopRecording = useCallback(() => {
        if (elapsedRef.current) clearInterval(elapsedRef.current);
        if (mediaRecorderRef.current?.state === 'recording') {
            mediaRecorderRef.current.stop();
        }
    }, []);

    const retakeRecording = useCallback(() => {
        if (recordedUrl) URL.revokeObjectURL(recordedUrl);
        setRecordedBlob(null);
        setRecordedUrl(null);
        setElapsed(0);
        startPreview(mode);
    }, [recordedUrl, mode, startPreview]);

    const handleUpload = useCallback(async () => {
        if (!recordedBlob) return;

        setState('uploading');
        setUploadProgress('Uploading recording...');
        setError(null);

        try {
            const result: UploadRecordingResponse = await api.uploadRecording(
                sessionId,
                recordedBlob,
                `recording-${Date.now()}.webm`
            );

            setUploadProgress('Assigning to scene...');

            await api.setSceneRecording(
                sessionId,
                sceneId,
                result.video_id,
                0,
                result.duration
            );

            setState('done');
            setUploadProgress('');
            onComplete(result.video_id, result.duration);
        } catch (err: unknown) {
            const message = err instanceof Error ? err.message : 'Upload failed';
            setError(message);
            setState('review'); // go back so they can retry
        }
    }, [recordedBlob, sessionId, sceneId, onComplete]);

    const formatElapsed = (seconds: number) => {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${m}:${s.toString().padStart(2, '0')}`;
    };

    // ====================================================================
    // Render
    // ====================================================================

    return (
        <div className="flex flex-col">
            {/* Error banner */}
            {error && (
                <div className="mx-4 mt-3 px-4 py-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg flex items-center gap-2">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 flex-shrink-0">
                        <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
                    </svg>
                    {error}
                    <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600">✕</button>
                </div>
            )}

            {/* ============================================================ */}
            {/* IDLE — Mode Selection */}
            {/* ============================================================ */}
            {state === 'idle' && (
                <div className="p-6 space-y-5">
                    <div className="text-center">
                        <div className="text-4xl mb-2">🎥</div>
                        <h3 className="text-lg font-semibold text-slate-800">Record a Video</h3>
                        <p className="text-sm text-slate-500 mt-1">Choose a recording mode to get started</p>
                    </div>

                    <div className="grid grid-cols-3 gap-3">
                        {([
                            { key: 'webcam' as const, icon: '📸', label: 'Webcam', desc: 'Record from camera' },
                            { key: 'screen' as const, icon: '🖥️', label: 'Screen', desc: 'Share your screen' },
                            { key: 'both' as const, icon: '🎬', label: 'PiP', desc: 'Screen + webcam' },
                        ]).map(opt => (
                            <button
                                key={opt.key}
                                onClick={() => setMode(opt.key)}
                                className={`p-4 rounded-xl border-2 text-center transition-all ${mode === opt.key
                                    ? 'border-teal-500 bg-teal-50 shadow-sm'
                                    : 'border-slate-200 hover:border-slate-300 bg-white'
                                    }`}
                            >
                                <div className="text-2xl mb-1">{opt.icon}</div>
                                <div className="text-sm font-medium text-slate-800">{opt.label}</div>
                                <div className="text-xs text-slate-500 mt-0.5">{opt.desc}</div>
                            </button>
                        ))}
                    </div>

                    <div className="flex justify-end gap-3">
                        <button
                            onClick={onCancel}
                            className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={() => startPreview(mode)}
                            className="px-5 py-2 text-sm font-medium text-white bg-teal-600 hover:bg-teal-700 rounded-lg transition-colors shadow-sm"
                        >
                            Start Preview
                        </button>
                    </div>
                </div>
            )}

            {/* ============================================================ */}
            {/* PREVIEW / COUNTDOWN / RECORDING */}
            {/* ============================================================ */}
            {(state === 'preview' || state === 'countdown' || state === 'recording') && (
                <div className="relative">
                    {/* Live video feed */}
                    <div className="relative bg-black rounded-t-lg overflow-hidden aspect-video">
                        <video
                            ref={liveVideoRef}
                            className="w-full h-full object-contain"
                            autoPlay
                            playsInline
                            muted
                        />

                        {/* Countdown overlay */}
                        {state === 'countdown' && (
                            <div className="absolute inset-0 flex items-center justify-center bg-black/50">
                                <div className="text-8xl font-bold text-white animate-ping-slow drop-shadow-2xl">
                                    {countdown}
                                </div>
                            </div>
                        )}

                        {/* Recording indicator */}
                        {state === 'recording' && (
                            <div className="absolute top-4 left-4 flex items-center gap-2 bg-black/70 px-3 py-1.5 rounded-full">
                                <span className="w-3 h-3 bg-red-500 rounded-full animate-pulse" />
                                <span className="text-white text-sm font-mono">{formatElapsed(elapsed)}</span>
                            </div>
                        )}
                    </div>

                    {/* Controls bar */}
                    <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-t border-slate-200 rounded-b-lg">
                        <button
                            onClick={() => {
                                if (state === 'recording') {
                                    stopRecording();
                                } else {
                                    stopAllStreams();
                                    setState('idle');
                                }
                            }}
                            className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-200 rounded-lg transition-colors"
                        >
                            {state === 'recording' ? 'Cancel' : 'Back'}
                        </button>

                        {state === 'preview' && (
                            <button
                                onClick={startCountdown}
                                className="px-6 py-2.5 text-sm font-medium text-white bg-red-500 hover:bg-red-600 rounded-full transition-colors shadow-lg flex items-center gap-2"
                            >
                                <span className="w-3 h-3 bg-white rounded-full" />
                                Record
                            </button>
                        )}

                        {state === 'recording' && (
                            <button
                                onClick={stopRecording}
                                className="px-6 py-2.5 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-full transition-colors shadow-lg flex items-center gap-2"
                            >
                                <span className="w-3 h-3 bg-white rounded-sm" />
                                Stop
                            </button>
                        )}

                        {state === 'countdown' && (
                            <div className="text-sm text-slate-500 italic">Get ready...</div>
                        )}
                    </div>
                </div>
            )}

            {/* ============================================================ */}
            {/* REVIEW */}
            {/* ============================================================ */}
            {state === 'review' && recordedUrl && (
                <div className="space-y-0">
                    <div className="bg-black rounded-t-lg overflow-hidden aspect-video">
                        <video
                            ref={reviewVideoRef}
                            src={recordedUrl}
                            className="w-full h-full object-contain"
                            controls
                            playsInline
                        />
                    </div>

                    <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-t border-slate-200 rounded-b-lg">
                        <div className="flex items-center gap-3">
                            <button
                                onClick={retakeRecording}
                                className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-200 rounded-lg transition-colors flex items-center gap-1.5"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                                    <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H4.598a.75.75 0 00-.75.75v3.634a.75.75 0 001.5 0v-2.033l.312.311a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm.137-7.848a.75.75 0 00-1.5 0v3.634a.75.75 0 00.75.75H18.332a.75.75 0 000-1.5h-2.433l.312-.31a5.5 5.5 0 00-9.201-2.467.75.75 0 101.06 1.06A4 4 0 0115.312 6.57l-.312.31v-3.304z" clipRule="evenodd" />
                                </svg>
                                Retake
                            </button>
                            <span className="text-xs text-slate-400">
                                {formatElapsed(elapsed)} recorded
                                {recordedBlob && ` • ${(recordedBlob.size / 1024 / 1024).toFixed(1)} MB`}
                            </span>
                        </div>

                        <button
                            onClick={handleUpload}
                            className="px-5 py-2 text-sm font-medium text-white bg-teal-600 hover:bg-teal-700 rounded-lg transition-colors shadow-sm flex items-center gap-2"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                                <path d="M9.25 13.25a.75.75 0 001.5 0V4.636l2.955 3.129a.75.75 0 001.09-1.03l-4.25-4.5a.75.75 0 00-1.09 0l-4.25 4.5a.75.75 0 101.09 1.03L9.25 4.636v8.614z" />
                                <path d="M3.5 12.75a.75.75 0 00-1.5 0v2.5A2.75 2.75 0 004.75 18h10.5A2.75 2.75 0 0018 15.25v-2.5a.75.75 0 00-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5z" />
                            </svg>
                            Use this Recording
                        </button>
                    </div>
                </div>
            )}

            {/* ============================================================ */}
            {/* UPLOADING */}
            {/* ============================================================ */}
            {state === 'uploading' && (
                <div className="p-8 flex flex-col items-center justify-center space-y-4">
                    <svg className="animate-spin h-8 w-8 text-teal-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    <p className="text-sm text-slate-600 font-medium">{uploadProgress}</p>
                    <p className="text-xs text-slate-400">This may take a moment for larger recordings</p>
                </div>
            )}
        </div>
    );
}
