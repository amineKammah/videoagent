'use client';

import { useState, useRef, useEffect, useCallback, useMemo, useImperativeHandle, forwardRef, ReactNode } from 'react';
import { useSessionStore } from '@/store/session';
import { api } from '@/lib/api';
import { VideoMetadata, StoryboardScene } from '@/lib/types';
import { SceneTimeline } from './SceneTimeline';

interface FeedbackNote {
    id: string;
    timestamp: number;
    feedback: string;
}

export interface VideoPlayerRef {
    seekTo: (time: number) => void;
    play: () => void;
    pause: () => void;
    getCurrentTime: () => number;
}

interface VideoPlayerProps {
    onTimeUpdate?: (currentTime: number) => void;
    onPlayChange?: (isPlaying: boolean) => void;
    overlay?: ReactNode;
    primaryAction?: ReactNode;
    hideTimeline?: boolean;
    className?: string;
}

export const VideoPlayer = forwardRef<VideoPlayerRef, VideoPlayerProps>(function VideoPlayer({
    onTimeUpdate,
    onPlayChange,
    overlay,
    primaryAction,
    hideTimeline = false,
    className
}, ref) {
    const session = useSessionStore(state => state.session);
    // ... rest of the component

    const scenes = useSessionStore(state => state.scenes);
    const setScenes = useSessionStore(state => state.setScenes);

    // State
    const [metadata, setMetadata] = useState<Record<string, VideoMetadata>>({});
    const [metadataLoading, setMetadataLoading] = useState(false);
    const [currentSceneIndex, setCurrentSceneIndex] = useState(0);
    const [isPlaying, setIsPlaying] = useState(false);
    const [playbackState, setPlaybackState] = useState<'video' | 'waiting_for_audio'>('video');
    const [error, setError] = useState<string | null>(null);

    // Controls State
    const [currentTime, setCurrentTime] = useState(0); // Global time

    // Notify parent of updates
    useEffect(() => {
        onTimeUpdate?.(currentTime);
    }, [currentTime, onTimeUpdate]);

    useEffect(() => {
        onPlayChange?.(isPlaying);
    }, [isPlaying, onPlayChange]);

    // Expose refs
    useImperativeHandle(ref, () => ({
        seekTo: (time: number) => {
            // We can use handleSeek but it expects an event. 
            // Ideally we refactor handleSeek to separate logic. 
            // Or construct a fake event.
            handleSeek({ target: { value: time.toString() } } as any);
        },
        play: () => {
            if (!isPlaying) togglePlay();
        },
        pause: () => {
            if (isPlaying) togglePlay();
        },
        getCurrentTime: () => currentTime
    }));

    const [isHoveringControls, setIsHoveringControls] = useState(false);
    const [volume, setVolume] = useState(1);
    const [isMuted, setIsMuted] = useState(false);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const controlsTimeoutRef = useRef<NodeJS.Timeout | null>(null);

    // Feedback State

    // Feedback State
    const [showFeedbackDialog, setShowFeedbackDialog] = useState(false);
    const [feedbackText, setFeedbackText] = useState('');
    const [feedbackTimestamp, setFeedbackTimestamp] = useState<number | null>(null);
    const [pendingFeedback, setPendingFeedback] = useState<{
        id: string;
        sceneNumber: number;
        relativeTime: number;
        feedback: string;
        timestamp: number;
        context: any;
    }[]>([]);

    const sendMessage = useSessionStore(state => state.sendMessage);

    // Export State
    const [isExporting, setIsExporting] = useState(false);
    const [exportError, setExportError] = useState<string | null>(null);

    const submitFeedback = () => {
        const sceneStartTime = segmentStarts[currentSceneIndex];
        const relativeTime = currentTime - sceneStartTime;
        const sceneNumber = currentSceneIndex + 1;

        const newItem = {
            id: crypto.randomUUID(),
            sceneNumber,
            relativeTime,
            feedback: feedbackText,
            timestamp: currentTime,
            context: {
                sceneId: activeScene?.scene_id,
                sceneNumber: sceneNumber,
                relativeTimestamp: relativeTime,
                sceneDescription: activeScene?.matched_scene?.description,
                globalDuration: totalDuration
            }
        };

        setPendingFeedback(prev => [...prev, newItem]);
        setShowFeedbackDialog(false);
        setFeedbackText('');
        setFeedbackTimestamp(null);
    };

    const removePendingItem = (id: string) => {
        setPendingFeedback(prev => prev.filter(item => item.id !== id));
    };

    const submitAllFeedback = async () => {
        if (pendingFeedback.length === 0) return;

        // Sort by timestamp
        const sorted = [...pendingFeedback].sort((a, b) => a.timestamp - b.timestamp);

        let message = "Here is a list of changes I want for the video:\n\n";
        sorted.forEach((item, index) => {
            message += `${index + 1}. **Scene ${item.sceneNumber} (${formatTime(item.relativeTime)})**: ${item.feedback}\n`;
        });

        try {
            await sendMessage(message);
            setPendingFeedback([]);
        } catch (e) {
            console.error("Failed to send batch feedback", e);
        }
    };

    const handleExport = async () => {
        if (!session?.id) return;

        setIsExporting(true);
        setExportError(null);

        try {
            // Call the render API
            const result = await api.renderVideo(session.id);

            if (result.render_result.success && result.render_result.output_path) {
                // Fetch the rendered video and trigger download
                const videoUrl = `/api/video?path=${encodeURIComponent(result.render_result.output_path)}`;
                const response = await fetch(videoUrl);
                const blob = await response.blob();

                // Create download link
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `exported-video-${new Date().toISOString().slice(0, 10)}.mp4`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
            } else {
                setExportError(result.render_result.error_message || 'Failed to render video');
            }
        } catch (e) {
            console.error("Export failed", e);
            setExportError(e instanceof Error ? e.message : 'Export failed');
        } finally {
            setIsExporting(false);
        }
    };

    // Refs
    // Refs
    const videoRef = useRef<HTMLVideoElement>(null);
    const audioRef = useRef<HTMLAudioElement>(null);
    const requestRef = useRef<number | undefined>(undefined);
    const isTransitioningRef = useRef(false);

    // Derived
    const activeScene = scenes[currentSceneIndex];
    const activeMetadata = activeScene?.matched_scene ? metadata[activeScene.matched_scene.source_video_id] : null;
    const hasMatchedScenes = scenes.some(s => s.matched_scene);

    // Global Timeline Calculation
    const { segmentStarts, totalDuration } = useMemo(() => {
        let current = 0;
        const starts: number[] = [];
        scenes.forEach(scene => {
            starts.push(current);
            const duration = (scene.matched_scene?.end_time || 0) - (scene.matched_scene?.start_time || 0);
            current += duration;
        });
        return { segmentStarts: starts, totalDuration: current };
    }, [scenes]);

    // Format time helper
    const formatTime = (seconds: number) => {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    };

    // Fetch Metadata
    useEffect(() => {
        const fetchMetadata = async () => {
            const idsToFetch = new Set<string>();
            scenes.forEach(scene => {
                if (scene.matched_scene?.source_video_id && !metadata[scene.matched_scene.source_video_id]) {
                    idsToFetch.add(scene.matched_scene.source_video_id);
                }
            });

            if (idsToFetch.size === 0) return;

            setMetadataLoading(true);
            try {
                const newMetadata = { ...metadata };
                await Promise.all(
                    Array.from(idsToFetch).map(async (id) => {
                        try {
                            const meta = await api.getVideoMetadata(id);
                            newMetadata[id] = meta;
                        } catch (e) {
                            console.error(`Failed to fetch metadata for ${id}`, e);
                        }
                    })
                );
                setMetadata(newMetadata);
            } catch (err) {
                console.error('Metadata fetch error', err);
            } finally {
                setMetadataLoading(false);
            }
        };

        if (hasMatchedScenes) {
            fetchMetadata();
        }
    }, [scenes, metadata, hasMatchedScenes]);

    // Playback Logic
    const playSegment = useCallback(async (sceneIndex: number, shouldPlay: boolean = true, reason: string = "unknown") => {
        console.log(`[playSegment] Transitioning to scene ${sceneIndex}. Reason: ${reason}`);
        const scene = scenes[sceneIndex];
        if (!scene || !scene.matched_scene) {
            if (sceneIndex < scenes.length - 1) {
                playSegment(sceneIndex + 1, shouldPlay, "skip-empty-scene");
            } else {
                setIsPlaying(false);
            }
            return;
        }

        // Mark transition start to ignore intermediate pause events
        if (shouldPlay) {
            isTransitioningRef.current = true;
        }

        try {
            const meta = metadata[scene.matched_scene.source_video_id];
            if (!meta || !videoRef.current) return;

            setCurrentSceneIndex(sceneIndex);

            // Load Video
            if (meta.path && videoRef.current.getAttribute('src') !== `/api/video?path=${encodeURIComponent(meta.path)}`) {
                videoRef.current.src = `/api/video?path=${encodeURIComponent(meta.path)}`;
                videoRef.current.load();
            }

            // Set Start Time
            videoRef.current.currentTime = scene.matched_scene.start_time;

            // Handle Voice Over
            if (scene.use_voice_over && scene.voice_over && scene.voice_over.audio_path && audioRef.current) {
                const audioSrc = `/api/video?path=${encodeURIComponent(scene.voice_over.audio_path)}`;
                if (audioRef.current.getAttribute('src') !== audioSrc) {
                    audioRef.current.src = audioSrc;
                    audioRef.current.load();
                }

                // Calculate Playback Rate
                const videoDuration = scene.matched_scene.end_time - scene.matched_scene.start_time;
                const audioDuration = scene.voice_over.duration;

                let rate = 1.0;
                // Only speed up if audio is longer than video
                if (videoDuration > 0 && audioDuration > videoDuration) {
                    rate = audioDuration / videoDuration;
                }
                // Cap at 2.0x, never go below 1.0x (don't slow down)
                rate = Math.min(2.0, rate);

                console.log(`[playSegment] Syncing Audio. VideoDur=${videoDuration.toFixed(2)}, AudioDur=${audioDuration.toFixed(2)}, CalcRate=${rate.toFixed(2)}`);

                audioRef.current.playbackRate = rate;
                console.log(`[playSegment] Applied playbackRate: ${audioRef.current.playbackRate}`);

                if (shouldPlay) {
                    try {
                        await audioRef.current.play();
                    } catch (e) {
                        console.error("Audio play failed", e);
                    }
                } else {
                    audioRef.current.pause();
                }
            } else {
                // No audio or audio failed
                if (audioRef.current) {
                    audioRef.current.pause();
                    audioRef.current.src = '';
                }
            }

            // Mute video if playing voice over
            // Play/Pause Video
            if (videoRef.current) {
                videoRef.current.muted = !!(scene.use_voice_over && scene.voice_over && scene.voice_over.audio_path);
                try {
                    if (shouldPlay) {
                        await videoRef.current.play();
                        setIsPlaying(true);
                        setPlaybackState('video');
                    } else {
                        videoRef.current.pause();
                        setIsPlaying(false);
                    }
                } catch (e) {
                    console.error("Video play failed", e);
                    setIsPlaying(false);
                }
            }
        } finally {
            // Transition done
            isTransitioningRef.current = false;
        }

    }, [scenes, metadata]);

    // React to Scene Source Changes (e.g. LLM updates or initial load)
    useEffect(() => {
        const scene = scenes[currentSceneIndex];
        if (!scene?.matched_scene) return;

        const meta = metadata[scene.matched_scene.source_video_id];
        if (!meta) return;

        if (videoRef.current) {
            const expectedSrc = `/api/video?path=${encodeURIComponent(meta.path)}`;
            const currentSrc = videoRef.current.getAttribute('src');

            // If source changed, reload. preserve playing state.
            if (currentSrc !== expectedSrc) {
                playSegment(currentSceneIndex, isPlaying, "source-changed");
            }
        }
    }, [scenes, currentSceneIndex, metadata, isPlaying, playSegment]);

    // Loop / Monitor
    useEffect(() => {
        const checkTime = () => {
            if (!videoRef.current) return;

            // Update global time for UI
            if (scenes[currentSceneIndex]?.matched_scene) {
                const sceneStart = scenes[currentSceneIndex].matched_scene!.start_time;
                const globalOffset = segmentStarts[currentSceneIndex];
                const currentSceneTime = Math.max(0, videoRef.current.currentTime - sceneStart);
                setCurrentTime(globalOffset + currentSceneTime);
            }

            if (!isPlaying) return;

            const scene = scenes[currentSceneIndex];
            if (!videoRef.current) return;
            if (!scene || !scene.matched_scene) return;

            // Check if video reached end
            if (videoRef.current && (videoRef.current.ended || videoRef.current.currentTime >= scene.matched_scene.end_time)) {
                // Guard against double-transition
                if (isTransitioningRef.current) return;

                console.log(`[checkTime] Video segment ended or reached end_time for scene ${currentSceneIndex}. Triggering transition.`);
                // Video finished segment

                // Prevent implicit pause from setting isPlaying(false)
                isTransitioningRef.current = true;
                if (!videoRef.current.paused) {
                    videoRef.current.pause();
                }

                // Check if Audio is still playing / has content left
                const audio = audioRef.current;
                let audioStillPlaying = false;

                if (scene.use_voice_over && audio) {
                    const isAudioPaused = audio.paused;
                    const isAudioEnded = audio.ended;
                    const audioTimeLeft = (audio.duration || 0) - audio.currentTime;
                    // We consider it playing if it's not paused OR if there is significant time left (even if paused momentarily by race condition)
                    // But if it's paused by USER, we shouldn't wait? 
                    // No, if video ends but audio has 5s left, we MUST wait, even if paused? 
                    // If video is paused, checkTime doesn't run.
                    // If video isn't paused (we are here), then audio shouldn't be paused unless it finished or failed.

                    audioStillPlaying = !isAudioEnded && (audioTimeLeft > 0.2);

                    console.log(`[checkTime] Video ended. Audio State: Paused=${isAudioPaused}, Ended=${isAudioEnded}, TimeLeft=${audioTimeLeft?.toFixed(2)}, Waiting=${audioStillPlaying}`);
                }

                if (playbackState !== 'waiting_for_audio' && audioStillPlaying) {
                    console.log(`[checkTime] Audio still has content (${(audio?.duration || 0) - (audio?.currentTime || 0)}s). Waiting.`);
                    setPlaybackState('waiting_for_audio');
                    isTransitioningRef.current = false;
                } else if (playbackState !== 'waiting_for_audio') {
                    console.log(`[checkTime] Audio considered finished. Advancing.`);
                    // Advance
                    if (currentSceneIndex < scenes.length - 1) {
                        // playSegment handles setting isTransitioningRef back to false via finally block
                        playSegment(currentSceneIndex + 1, true, "checkTime-auto");
                    } else {
                        console.log(`[checkTime] Last scene ended. Resetting playback.`);
                        setIsPlaying(false);
                        setCurrentSceneIndex(0); // Reset to start
                        isTransitioningRef.current = false;
                    }
                }
            }

            if (isPlaying) {
                requestRef.current = requestAnimationFrame(checkTime);
            }
        };

        requestRef.current = requestAnimationFrame(checkTime);
        return () => {
            if (requestRef.current) cancelAnimationFrame(requestRef.current);
        };
    }, [isPlaying, currentSceneIndex, scenes, playSegment, segmentStarts, playbackState]); // Added playbackState dependency

    // Audio Ended Handler (for safety)
    useEffect(() => {
        const audio = audioRef.current;
        const video = videoRef.current;

        const handleAudioEnded = () => {
            if (playbackState === 'waiting_for_audio') {
                if (currentSceneIndex < scenes.length - 1) {
                    playSegment(currentSceneIndex + 1, true);
                } else {
                    setIsPlaying(false);
                    setCurrentSceneIndex(0);
                }
            }
        };

        // Handle native video 'ended' event (backup for RequestAnimationFrame)
        const handleVideoEnded = () => {
            if (isTransitioningRef.current) return;

            // Only act if not already waiting for audio
            if (playbackState !== 'waiting_for_audio') {
                // Trigger transition logic
                isTransitioningRef.current = true;

                // Check if Audio is still playing
                const scene = scenes[currentSceneIndex];
                const audio = audioRef.current;
                let audioStillPlaying = false;

                if (scene?.use_voice_over && audio) {
                    const isAudioEnded = audio.ended;
                    const audioTimeLeft = (audio.duration || 0) - audio.currentTime;
                    audioStillPlaying = !isAudioEnded && (audioTimeLeft > 0.2);
                    console.log(`[handleVideoEnded] Audio State: Ended=${isAudioEnded}, TimeLeft=${audioTimeLeft?.toFixed(2)}, Waiting=${audioStillPlaying}`);
                }

                if (audioStillPlaying) {
                    setPlaybackState('waiting_for_audio');
                    isTransitioningRef.current = false;
                } else {
                    if (currentSceneIndex < scenes.length - 1) {
                        playSegment(currentSceneIndex + 1, true);
                    } else {
                        setIsPlaying(false);
                        setCurrentSceneIndex(0);
                        isTransitioningRef.current = false;
                    }
                }
            }
        };

        const handleVideoPlay = () => {
            setIsPlaying(true);
            if (audioRef.current && !audioRef.current.ended && audioRef.current.src) {
                audioRef.current.play().catch(console.error);
            }
        };

        const handleVideoPause = () => {
            // Ignore pause events if we are programmatically transitioning
            if (isTransitioningRef.current) return;

            // Also ignore system pauses if we are explicitly waiting for audio to finish
            // (e.g. video ended but audio is playing). 
            // Note: User manual pause bypasses this by calling setIsPlaying(false) and audio.pause() directly in togglePlay
            if (playbackState === 'waiting_for_audio') return;

            setIsPlaying(false);
            if (audioRef.current) {
                audioRef.current.pause();
            }
        };

        const handleVideoSeek = () => {
            if (audioRef.current && videoRef.current) {
                const scene = scenes[currentSceneIndex];
                if (scene && scene.matched_scene) {
                    // Sync audio time relative to scene start
                    const relativeTime = videoRef.current.currentTime - scene.matched_scene.start_time;
                    // Only seek if within bounds
                    if (relativeTime >= 0) {
                        const audioTime = relativeTime * (audioRef.current.playbackRate || 1);
                        if (isFinite(audioTime)) {
                            audioRef.current.currentTime = audioTime;
                        }
                    }
                }
            }
        };

        if (video) {
            video.addEventListener('play', handleVideoPlay);
            video.addEventListener('pause', handleVideoPause);
            video.addEventListener('seeking', handleVideoSeek);
            video.addEventListener('ended', handleVideoEnded); // Add ended listener
        }

        audio?.addEventListener('ended', handleAudioEnded);
        audio?.addEventListener('ratechange', () => console.log(`[Audio Event] ratechange: ${audio.playbackRate}`));

        return () => {
            audio?.removeEventListener('ended', handleAudioEnded);
            if (video) {
                video.removeEventListener('play', handleVideoPlay);
                video.removeEventListener('pause', handleVideoPause);
                video.removeEventListener('seeking', handleVideoSeek);
                video.removeEventListener('ended', handleVideoEnded);
            }
        };
    }, [playbackState, currentSceneIndex, scenes, playSegment]);


    const togglePlay = () => {
        if (isPlaying) {
            setIsPlaying(false);
            videoRef.current?.pause();
            audioRef.current?.pause();
        } else {
            // setIsPlaying(true); // playSegment handles this
            playSegment(currentSceneIndex, true, "toggle-play");
        }
    };

    const handleTrimChange = (start: number, end: number, handle: 'start' | 'end' = 'start') => {
        // Optimistic update
        // Deep copy to ensure React detects changes correctly
        const updatedScenes = scenes.map(s => ({ ...s }));
        const scene = updatedScenes[currentSceneIndex];

        if (scene && scene.matched_scene) {
            scene.matched_scene.start_time = start;
            scene.matched_scene.end_time = end;
            setScenes(updatedScenes);

            // Update video preview if paused - seek to the handle being dragged
            if (!isPlaying && videoRef.current) {
                // Seek to the appropriate position based on which handle is being dragged
                videoRef.current.currentTime = handle === 'start' ? start : end;
            }
        }
    };

    const handleTrimEnd = async (start: number, end: number) => {
        // Final commit to backend
        const updatedScenes = scenes.map(s => ({ ...s }));
        const scene = updatedScenes[currentSceneIndex];

        if (scene && scene.matched_scene) {
            scene.matched_scene.start_time = start; // Ensure latest value is used
            scene.matched_scene.end_time = end;

            // We likely already updated state in handleTrimChange, but let's be safe
            setScenes(updatedScenes);

            try {
                console.log("Saving trim to backend...");
                await api.updateStoryboard(session!.id, updatedScenes);
                console.log("Trim saved.");
            } catch (e) {
                console.error("Failed to save trim", e);
                // Revert? For now, just log error.
            }
        }
    };

    const previewLoop = () => {
        // Just play current segment
        if (isPlaying) {
            togglePlay(); // Stop
        } else {
            // setIsPlaying(true);
            // Logic to ONLY play this segment loop? 
            // For now just play normal flow starting here
            playSegment(currentSceneIndex, true, "preview-loop");
        }
    };

    const handleReportIssue = () => {
        if (videoRef.current) {
            videoRef.current.pause();
            setIsPlaying(false);
            setFeedbackTimestamp(videoRef.current.currentTime);
            setShowFeedbackDialog(true);
        }
    };



    const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
        const newTime = parseFloat(e.target.value);
        setCurrentTime(newTime);

        // Find target scene
        let targetSceneIndex = 0;
        for (let i = 0; i < segmentStarts.length; i++) {
            if (newTime >= segmentStarts[i]) {
                targetSceneIndex = i;
            } else {
                break;
            }
        }

        // Calculate offset within target scene
        const sceneGlobalStart = segmentStarts[targetSceneIndex];
        const offsetInScene = newTime - sceneGlobalStart;
        const targetScene = scenes[targetSceneIndex];

        if (targetSceneIndex !== currentSceneIndex) {
            playSegment(targetSceneIndex, isPlaying, "seek").then(() => {
                if (videoRef.current && targetScene.matched_scene) {
                    videoRef.current.currentTime = targetScene.matched_scene.start_time + offsetInScene;
                }
            });
        } else {
            if (videoRef.current && targetScene.matched_scene) {
                videoRef.current.currentTime = targetScene.matched_scene.start_time + offsetInScene;
            }
        }
    };

    const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const val = parseFloat(e.target.value);
        setVolume(val);
        if (videoRef.current) videoRef.current.volume = val;
        setIsMuted(val === 0);
    };

    const toggleFullscreen = () => {
        if (!document.fullscreenElement) {
            videoRef.current?.parentElement?.requestFullscreen();
            setIsFullscreen(true);
        } else {
            document.exitFullscreen();
            setIsFullscreen(false);
        }
    };


    if (!hasMatchedScenes) return null;

    return (
        <div className="w-full flex flex-col">


            {/* Video Area (Black) */}
            <div className="w-full max-w-5xl mx-auto aspect-video relative bg-black flex flex-col overflow-hidden">

                {/* Main Player */}
                <div className="w-full h-full relative flex items-center justify-center">
                    <video
                        ref={videoRef}
                        className="w-full h-full object-contain"
                        playsInline
                    />

                    {/* Custom Controls Overlay */}
                    <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-4 flex flex-col gap-2 z-20 group">
                        {/* Scrubber */}
                        <input
                            type="range"
                            min={0}
                            max={totalDuration}
                            step={0.1}
                            value={currentTime}
                            onChange={handleSeek}
                            className="w-full h-1 bg-white/30 rounded-lg appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-teal-400 [&::-webkit-slider-thumb]:rounded-full hover:[&::-webkit-slider-thumb]:bg-teal-300"
                        />

                        <div className="flex items-center justify-between text-white">
                            <div className="flex items-center gap-4">
                                <button onClick={togglePlay} className="hover:text-teal-400">
                                    {isPlaying ? (
                                        <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" /></svg>
                                    ) : (
                                        <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
                                    )}
                                </button>

                                <div className="flex items-center gap-2 group/vol">
                                    <button onClick={() => {
                                        const newMuted = !isMuted;
                                        setIsMuted(newMuted);
                                        if (videoRef.current) videoRef.current.muted = newMuted;
                                    }}>
                                        {isMuted || volume === 0 ? (
                                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" /></svg>
                                        ) : (
                                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" /></svg>
                                        )}
                                    </button>
                                    <input
                                        type="range"
                                        min={0}
                                        max={1}
                                        step={0.1}
                                        value={volume}
                                        onChange={handleVolumeChange}
                                        className="w-16 h-1 bg-white/30 rounded-lg appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-2 [&::-webkit-slider-thumb]:h-2 [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full"
                                    />
                                </div>

                                <span className="text-xs font-mono opacity-80">
                                    {formatTime(currentTime)} / {formatTime(totalDuration)}
                                </span>
                            </div>

                            <div className="flex items-center gap-2">
                                {/* Export Button */}
                                <button
                                    onClick={handleExport}
                                    disabled={isExporting}
                                    className="hover:text-teal-400 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                    title={isExporting ? "Exporting..." : "Export Video"}
                                >
                                    {isExporting ? (
                                        <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                        </svg>
                                    ) : (
                                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                        </svg>
                                    )}
                                </button>

                                {/* Fullscreen Button */}
                                <button onClick={toggleFullscreen} className="hover:text-teal-400">
                                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" /></svg>
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Primary Action Button (Floating Bottom Left) */}
                    <div className="absolute bottom-20 left-4 z-30">
                        {primaryAction ? primaryAction : (
                            <button
                                onClick={handleReportIssue}
                                className="group bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium px-4 py-2 rounded-full shadow-lg flex items-center gap-2 transition-all hover:scale-105 hover:shadow-teal-500/20 border border-transparent hover:border-teal-400"
                            >
                                <svg className="w-4 h-4 text-teal-100 group-hover:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                                </svg>
                                Request Change
                            </button>
                        )}
                    </div>
                    {/* Hidden Audio for VO */}
                    <audio ref={audioRef} className="hidden" />

                    {/* Overlays */}
                    {metadataLoading && (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-white">
                            Loading assets...
                        </div>
                    )}

                    {/* Current Scene Indicator */}
                    <div className="absolute top-4 left-4 bg-black/50 px-2 py-1 rounded text-white text-xs backdrop-blur-sm">
                        Scene {currentSceneIndex + 1}: {activeScene?.matched_scene?.description?.slice(0, 30)}...
                    </div>
                </div>
            </div>

            {/* Timeline & Feedback Footer */}
            <div className="bg-white border-t border-slate-200 px-0 py-2">
                {/* Scene Timeline */}
                <SceneTimeline
                    scenes={scenes}
                    metadata={metadata}
                    currentSceneIndex={currentSceneIndex}
                    onSceneSelect={(idx) => {
                        // Select and Pause
                        playSegment(idx, false, "manual-select");
                    }}
                    onTrimChange={handleTrimChange}
                    onTrimEnd={handleTrimEnd}
                    isPlaying={isPlaying}
                />

                {/* Pending Feedback List */}
                {pendingFeedback.length > 0 && (
                    <div className="mt-4 pt-4 border-t border-slate-100 animate-slide-in">
                        <div className="flex items-center justify-between mb-3">
                            <h4 className="font-semibold text-slate-800 text-sm flex items-center gap-2">
                                <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                                Pending Changes ({pendingFeedback.length})
                            </h4>
                            <button
                                onClick={submitAllFeedback}
                                className="bg-teal-600 hover:bg-teal-700 text-white text-xs font-semibold px-3 py-1.5 rounded-lg flex items-center gap-2 transition-colors shadow-sm"
                            >
                                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path></svg>
                                Submit All to Agent
                            </button>
                        </div>

                        <div className="space-y-2 max-h-48 overflow-y-auto pr-1 custom-scrollbar">
                            {pendingFeedback.map((item) => (
                                <div key={item.id} className="bg-slate-50 border border-slate-200 rounded-md p-2.5 flex items-start gap-3 group">
                                    <div className="flex-shrink-0 mt-0.5">
                                        <div className="w-5 h-5 bg-teal-100 text-teal-700 rounded flex items-center justify-center text-[10px] font-bold">
                                            {item.sceneNumber}
                                        </div>
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-0.5">
                                            <span className="text-[10px] font-mono text-slate-500 bg-slate-200 px-1 rounded">{formatTime(item.relativeTime)}</span>
                                        </div>
                                        <p className="text-sm text-slate-700 leading-snug break-words">{item.feedback}</p>
                                    </div>
                                    <button
                                        onClick={() => removePendingItem(item.id)}
                                        className="text-slate-400 hover:text-red-500 p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                                        title="Remove note"
                                    >
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* Feedback Dialog Overlay */}
            {showFeedbackDialog && (
                <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
                    <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6 animate-slide-in relative">
                        <h3 className="text-lg font-semibold text-slate-800 mb-2">Share Feedback with Agent</h3>
                        <p className="text-sm text-slate-500 mb-4">
                            What do you like? What should be fixed? The agent will use this to improve the video.
                            <br />
                            <span className="font-mono bg-slate-100 px-1 rounded text-xs mt-1 inline-block">Timestamp: {formatTime(currentTime)}</span>
                        </p>

                        <textarea
                            className="w-full border border-slate-300 rounded-lg p-3 text-sm focus:ring-2 focus:ring-teal-500 focus:border-teal-500 outline-none h-32 resize-none"
                            placeholder="e.g. 'I like this shot', 'Music is too loud', 'Cut this part out'..."
                            value={feedbackText}
                            onChange={(e) => setFeedbackText(e.target.value)}
                            autoFocus
                        />

                        <div className="flex justify-end gap-2 mt-4">
                            <button
                                onClick={() => setShowFeedbackDialog(false)}
                                className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded text-sm font-medium"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={submitFeedback}
                                disabled={!feedbackText.trim()}
                                className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                Submit Feedback
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}); // End forwardRef
