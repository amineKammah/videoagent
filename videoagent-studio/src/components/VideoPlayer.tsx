'use client';

import { useState, useRef, useEffect } from 'react';
import { useSessionStore } from '@/store/session';
import { api } from '@/lib/api';
import { StoryboardScene } from '@/lib/types';

interface RenderResult {
    success: boolean;
    output_path?: string;
    error_message?: string;
    timestamp?: number; // Added for cache busting
}

interface FeedbackNote {
    id: string;
    timestamp: number;
    feedback: string;
}

export function VideoPlayer() {
    const session = useSessionStore(state => state.session);
    const scenes = useSessionStore(state => state.scenes);
    const isProcessing = useSessionStore(state => state.isProcessing);
    // Using hooks for actions ensures we catch updates and have proper binding
    const setProcessing = useSessionStore(state => state.setProcessing);
    const clearEvents = useSessionStore(state => state.clearEvents);
    const sendMessage = useSessionStore(state => state.sendMessage);

    const [isRendering, setIsRendering] = useState(false);
    const [renderResult, setRenderResult] = useState<RenderResult | null>(null);
    const [error, setError] = useState<string | null>(null);

    // Feedback state
    const [isReporting, setIsReporting] = useState(false);
    const [currentTimestamp, setCurrentTimestamp] = useState<number | null>(null);
    const [feedbackText, setFeedbackText] = useState('');
    const [feedbackList, setFeedbackList] = useState<FeedbackNote[]>([]);
    const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);

    const videoRef = useRef<HTMLVideoElement>(null);

    // Only show if at least one scene has a matched clip
    const hasMatchedScenes = scenes.some(s => s.matched_scene);

    if (!hasMatchedScenes) {
        return null;
    }

    const handleRender = async () => {
        if (!session) return;

        setIsRendering(true);
        setError(null);
        setFeedbackList([]); // Clear previous feedback on new render

        try {
            const response = await api.renderVideo(session.id);
            setRenderResult({
                ...response.render_result,
                timestamp: Date.now() // Add timestamp to force reload
            });

            // Auto-reload video element if it exists
            if (videoRef.current) {
                videoRef.current.load();
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Render failed');
        } finally {
            setIsRendering(false);
        }
    };

    const handleReportProblem = () => {
        if (!videoRef.current) return;

        // Pause the video and capture timestamp
        videoRef.current.pause();
        setCurrentTimestamp(videoRef.current.currentTime);
        setIsReporting(true);
        setFeedbackText('');
    };

    const handleAddNote = () => {
        if (currentTimestamp === null || !feedbackText.trim()) return;

        const newNote: FeedbackNote = {
            id: crypto.randomUUID(),
            timestamp: currentTimestamp,
            feedback: feedbackText.trim(),
        };

        setFeedbackList(prev => [...prev, newNote].sort((a, b) => a.timestamp - b.timestamp));

        // Reset form but don't clear list
        setIsReporting(false);
        setCurrentTimestamp(null);
        setFeedbackText('');
    };

    const handleCancelNote = () => {
        setIsReporting(false);
        setCurrentTimestamp(null);
        setFeedbackText('');
    };

    const handleDeleteNote = (id: string) => {
        setFeedbackList(prev => prev.filter(note => note.id !== id));
    };

    // Helper to find scene info from timestamp
    const getSceneContext = (timestamp: number): string => {
        // Filter to only scenes that are likely in the video (have matched scenes)
        // Assuming the renderer skips scenes without matches
        const activeScenes = scenes.filter(s => s.matched_scene);

        let remainingTime = timestamp;

        for (let i = 0; i < activeScenes.length; i++) {
            const scene = activeScenes[i];
            if (!scene.matched_scene) continue; // Should be handled by filter but for type safety

            const duration = scene.matched_scene.end_time - scene.matched_scene.start_time;

            if (remainingTime < duration || i === activeScenes.length - 1) {
                // Found the scene (or it's the last one)
                const offset = Math.max(0, remainingTime); // Ensure non-negative
                return `(Scene ${i + 1}: "${scene.title}", at ${offset.toFixed(1)}s)`;
            }

            remainingTime -= duration;
        }

        return "";
    };

    const handleSubmitAllFeedback = async () => {
        if (!session || feedbackList.length === 0) {
            console.log('Skipping submit: No session or feedback list empty');
            return;
        }

        console.log('Submitting feedback...');
        setIsSubmittingFeedback(true);

        // Format the feedback message for the LLM
        let feedbackMessage = "I reviewed the video and found the following issues that need fixing:\n\n";

        feedbackList.forEach((note, index) => {
            const context = getSceneContext(note.timestamp);
            feedbackMessage += `${index + 1}. At timestamp ${formatTimestamp(note.timestamp)} ${context}: "${note.feedback}"\n`;
        });

        feedbackMessage += "\nPlease fix these issues and update the storyboard accordingly.";
        console.log('Feedback message:', feedbackMessage);

        try {
            // Clear events first
            clearEvents();

            // Use the store's sendMessage action
            await sendMessage(feedbackMessage);

            console.log('Feedback submitted successfully');

            // Clear feedback list after successful submission
            setFeedbackList([]);

        } catch (err) {
            console.error('Submission error:', err);
            setError(err instanceof Error ? err.message : 'Failed to submit feedback');
            setProcessing(false); // Ensure processing is reset on error if sendMessage didn't do it
        } finally {
            setIsSubmittingFeedback(false);
        }
    };

    const formatTimestamp = (seconds: number): string => {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        const ms = Math.floor((seconds % 1) * 100);
        return `${mins}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`;
    };

    const jumpToTimestamp = (seconds: number) => {
        if (videoRef.current) {
            videoRef.current.currentTime = seconds;
            videoRef.current.pause();
        }
    };

    const canSubmit = !isSubmittingFeedback && !isProcessing && feedbackList.length > 0;

    return (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-4">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h3 className="font-semibold text-slate-800">Rendered Video</h3>
                    <p className="text-xs text-slate-500">Render your storyboard to preview the final video</p>
                </div>
                <button
                    onClick={handleRender}
                    disabled={!session || isRendering || isProcessing}
                    className="px-4 py-2 bg-teal-600 text-white text-sm font-medium rounded-lg
                     hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors duration-200 flex items-center gap-2"
                >
                    {isRendering ? (
                        <>
                            <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                            Rendering...
                        </>
                    ) : (
                        <>
                            🎬 Render Video
                        </>
                    )}
                </button>
            </div>

            {error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600 mb-4">
                    {error}
                </div>
            )}

            {renderResult && !renderResult.success && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600 mb-4">
                    {renderResult.error_message || 'Render failed'}
                </div>
            )}

            {/* Video player */}
            {renderResult?.success && renderResult.output_path && (
                <div className="space-y-3">
                    <div className="bg-slate-900 rounded-lg overflow-hidden">
                        <video
                            ref={videoRef}
                            controls
                            className="w-full"
                            key={renderResult.timestamp} // Force remount on new timestamp
                            src={`/api/video?path=${encodeURIComponent(renderResult.output_path)}&t=${renderResult.timestamp || Date.now()}`}
                        >
                            Your browser does not support the video tag.
                        </video>
                    </div>

                    {/* Controls bar */}
                    {!isSubmittingFeedback && !isProcessing && (
                        <div className="flex items-center justify-between">
                            <button
                                onClick={handleReportProblem}
                                disabled={isReporting}
                                className="px-3 py-1.5 text-sm text-amber-700 bg-amber-50 border border-amber-200 
                           rounded-lg hover:bg-amber-100 disabled:opacity-50 disabled:cursor-not-allowed
                           transition-colors duration-200 flex items-center gap-2"
                            >
                                🐛 Add Note at Current Time
                            </button>
                            <div className="flex items-center gap-2">
                                <span className="text-xs text-green-600 font-medium">✓ Render complete</span>
                            </div>
                        </div>
                    )}

                    {/* Add Note Form */}
                    {isReporting && currentTimestamp !== null && (
                        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 space-y-3 animate-slide-in">
                            <div className="flex items-center justify-between">
                                <div>
                                    <h4 className="font-medium text-amber-800">Add Feedback Note</h4>
                                    <p className="text-xs text-amber-600">
                                        Timestamp: <span className="font-mono">{formatTimestamp(currentTimestamp)}</span>
                                        <span className="ml-2 text-amber-500">
                                            {getSceneContext(currentTimestamp)}
                                        </span>
                                    </p>
                                </div>
                                <button
                                    onClick={handleCancelNote}
                                    className="text-amber-600 hover:text-amber-800 text-sm"
                                >
                                    Cancel
                                </button>
                            </div>

                            <textarea
                                value={feedbackText}
                                onChange={(e) => setFeedbackText(e.target.value)}
                                autoFocus
                                placeholder="Describe the issue you see here..."
                                className="w-full rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm 
                           placeholder:text-amber-400 focus:border-amber-500 focus:outline-none 
                           focus:ring-2 focus:ring-amber-500/20 resize-none"
                                rows={2}
                            />

                            <button
                                onClick={handleAddNote}
                                disabled={!feedbackText.trim()}
                                className="w-full px-4 py-2 bg-amber-600 text-white text-sm font-medium rounded-lg
                           hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed
                           transition-colors duration-200"
                            >
                                Add Note
                            </button>
                        </div>
                    )}

                    {/* Feedback List */}
                    {feedbackList.length > 0 && (
                        <div className="border border-slate-200 rounded-lg overflow-hidden bg-slate-50 mt-4">
                            <div className="px-4 py-2 border-b border-slate-200 bg-slate-100 flex justify-between items-center">
                                <h4 className="font-semibold text-slate-700 text-sm">Feedback Notes ({feedbackList.length})</h4>
                            </div>
                            <div className="max-h-60 overflow-y-auto">
                                {feedbackList.map((note, index) => (
                                    <div key={note.id} className="p-3 border-b border-slate-200 last:border-0 hover:bg-slate-50 flex gap-3">
                                        <button
                                            onClick={() => jumpToTimestamp(note.timestamp)}
                                            className="text-xs font-mono bg-slate-200 text-slate-700 px-1.5 py-0.5 rounded hover:bg-slate-300 h-fit whitespace-nowrap"
                                            title="Jump to timestamp"
                                        >
                                            {formatTimestamp(note.timestamp)}
                                        </button>
                                        <div className="flex-1">
                                            <p className="text-xs text-slate-400 mb-0.5">{getSceneContext(note.timestamp)}</p>
                                            <p className="text-sm text-slate-700">{note.feedback}</p>
                                        </div>
                                        <button
                                            onClick={() => handleDeleteNote(note.id)}
                                            className="text-slate-400 hover:text-red-600 transition-colors"
                                            title="Delete note"
                                        >
                                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                                                <path fillRule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z" clipRule="evenodd" />
                                            </svg>
                                        </button>
                                    </div>
                                ))}
                            </div>
                            <div className="p-3 bg-slate-50 border-t border-slate-200">
                                <button
                                    onClick={handleSubmitAllFeedback}
                                    disabled={!canSubmit}
                                    className="w-full px-4 py-2 bg-teal-600 text-white text-sm font-medium rounded-lg
                             hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed
                             transition-colors duration-200 flex items-center justify-center gap-2"
                                >
                                    {isSubmittingFeedback ? (
                                        <>
                                            <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                                            </svg>
                                            Submitting Feedback...
                                        </>
                                    ) : (
                                        <>
                                            Submit {feedbackList.length} Issue{feedbackList.length !== 1 ? 's' : ''} to LLM
                                        </>
                                    )}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Empty state before first render */}
            {!renderResult && !isRendering && (
                <div className="text-center py-6 text-slate-400">
                    <p className="text-sm">Click "Render Video" to generate the final video</p>
                </div>
            )}
        </div>
    );
}
