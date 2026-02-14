'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSessionStore } from '@/store/session';
import { StoryboardScene, Feedback } from '@/lib/types';
import { api } from '@/lib/api';
import { FeedbackControl } from './FeedbackControl';

const GENERATED_SOURCE_PREFIX = 'generated:';

function isGeneratedScene(scene: StoryboardScene): boolean {
    const sourceVideoId = scene.matched_scene?.source_video_id ?? '';
    return sourceVideoId.startsWith(GENERATED_SOURCE_PREFIX);
}

function getSceneMatchLabel(scene: StoryboardScene): 'Generated' | 'Matched' {
    return isGeneratedScene(scene) ? 'Generated' : 'Matched';
}

function formatMatchedSource(sourceVideoId: string): string {
    if (!sourceVideoId) {
        return '';
    }

    if (sourceVideoId.startsWith(GENERATED_SOURCE_PREFIX)) {
        const [, runId = '', assetName = ''] = sourceVideoId.split(':');
        const shortRunId = runId.slice(0, 8);
        const safeAssetName = assetName || 'generated_clip.mp4';
        const compactAssetName = safeAssetName.length > 48
            ? `${safeAssetName.slice(0, 45)}...`
            : safeAssetName;
        return shortRunId
            ? `generated/${compactAssetName} (${shortRunId})`
            : `generated/${compactAssetName}`;
    }

    const filename = sourceVideoId.split('/').filter(Boolean).pop() || sourceVideoId;
    return filename.length > 64 ? `${filename.slice(0, 61)}...` : filename;
}

export function Storyboard() {
    const { scenes, session } = useSessionStore();
    const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
    const [feedbackMap, setFeedbackMap] = useState<Record<string, Feedback>>({});

    // Load feedback when session loads
    useEffect(() => {
        if (!session?.id) return;

        const loadFeedback = async () => {
            try {
                const allFeedback = await api.listFeedback(session.id);
                const map: Record<string, Feedback> = {};
                allFeedback.forEach(f => {
                    const key = f.target_type === 'storyboard' ? 'storyboard' : `scene:${f.target_id}`;
                    map[key] = f;
                });
                setFeedbackMap(map);
            } catch (err) {
                console.error('Failed to load feedback:', err);
            }
        };

        loadFeedback();
    }, [session?.id]);

    const handleFeedbackUpdate = (feedback: Feedback) => {
        const key = feedback.target_type === 'storyboard' ? 'storyboard' : `scene:${feedback.target_id}`;
        setFeedbackMap(prev => ({ ...prev, [key]: feedback }));
    };

    // Handle keyboard navigation
    useEffect(() => {
        if (selectedIndex === null) return;

        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                setSelectedIndex(null);
            } else if (e.key === 'ArrowLeft') {
                e.preventDefault();
                setSelectedIndex(prev => prev !== null && prev > 0 ? prev - 1 : prev);
            } else if (e.key === 'ArrowRight') {
                e.preventDefault();
                setSelectedIndex(prev => prev !== null && prev < scenes.length - 1 ? prev + 1 : prev);
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [selectedIndex, scenes.length]);

    if (scenes.length === 0) {
        return (
            <div className="flex-1 flex items-center justify-center p-8 text-slate-400">
                <div className="text-center">
                    <div className="text-6xl mb-4">🎬</div>
                    <p className="text-lg font-medium">No storyboard yet</p>
                    <p className="text-sm mt-2">
                        Enter a project brief above or chat with the LLM to create a storyboard
                    </p>
                </div>
            </div>
        );
    }

    return (
        <>


            {/* Horizontal scrolling container */}
            <div className="relative group">
                <div
                    id="storyboard-container"
                    className="flex-1 overflow-x-auto p-4 scroll-smooth snap-x snap-mandatory hide-scrollbar"
                >
                    <div className="flex gap-3 min-w-max">
                        {scenes.map((scene, index) => (
                            <SceneCard
                                key={scene.scene_id}
                                scene={scene}
                                index={index}
                                onClick={() => setSelectedIndex(index)}
                                feedback={feedbackMap[`scene:${scene.scene_id}`]}
                            />
                        ))}
                    </div>
                </div>

                {/* Scroll Indicators / Buttons */}
                <div className="absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-white to-transparent pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity" />
                <div className="absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-white to-transparent pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity" />

                <button
                    onClick={() => document.getElementById('storyboard-container')?.scrollBy({ left: -200, behavior: 'smooth' })}
                    className="absolute left-2 top-1/2 -translate-y-1/2 p-2 bg-white/90 shadow-md rounded-full text-slate-600 hover:text-teal-600 hover:bg-white transition-all opacity-0 group-hover:opacity-100 focus:opacity-100"
                    aria-label="Scroll left"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                        <path fillRule="evenodd" d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z" clipRule="evenodd" />
                    </svg>
                </button>
                <button
                    onClick={() => document.getElementById('storyboard-container')?.scrollBy({ left: 200, behavior: 'smooth' })}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-2 bg-white/90 shadow-md rounded-full text-slate-600 hover:text-teal-600 hover:bg-white transition-all opacity-0 group-hover:opacity-100 focus:opacity-100"
                    aria-label="Scroll right"
                >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                        <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
                    </svg>
                </button>
            </div>

            {/* Storyboard-level Feedback */}
            {session && (
                <div className="mx-4 mt-2 flex justify-end">
                    <FeedbackControl
                        sessionId={session.id}
                        targetType="storyboard"
                        targetId={null}
                        initialFeedback={feedbackMap['storyboard'] || null}
                        onFeedbackUpdate={handleFeedbackUpdate}
                        variant="minimal"
                    />
                </div>
            )}

            {/* Modal for expanded view */}
            {selectedIndex !== null && (
                <SceneModal
                    scenes={scenes}
                    currentIndex={selectedIndex}
                    onClose={() => setSelectedIndex(null)}
                    onNavigate={setSelectedIndex}
                    feedbackMap={feedbackMap}
                    onFeedbackUpdate={handleFeedbackUpdate}
                />
            )}
        </>
    );
}

interface SceneCardProps {
    scene: StoryboardScene;
    index: number;
    onClick: () => void;
    feedback?: Feedback;
}

function SceneCard({ scene, index, onClick, feedback }: SceneCardProps) {
    const sceneLabel = getSceneMatchLabel(scene);

    return (
        <button
            onClick={onClick}
            className="w-44 flex-shrink-0 snap-center bg-white rounded-xl border border-slate-200 p-4 
                       hover:border-teal-400 hover:shadow-lg hover:-translate-y-1 hover:bg-slate-50
                       transition-all duration-300 ease-out text-left group
                       focus:outline-none focus:ring-2 focus:ring-teal-500/50"
        >
            <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-slate-400 font-mono">
                    Scene {index + 1}
                </span>
                {scene.matched_scene && (
                    <span className="w-2 h-2 rounded-full bg-green-500" title={sceneLabel} />
                )}
            </div>
            <h4 className="font-medium text-slate-800 text-sm line-clamp-2 leading-tight">
                {scene.title}
            </h4>

            {/* Feedback Indicator */}
            {feedback && (
                <div className="absolute bottom-3 right-3">
                    {feedback.rating === 'up' ? (
                        <div className="bg-green-100 text-green-700 p-1 rounded-full shadow-sm">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3 h-3">
                                <path d="M1 8.25a1.25 1.25 0 1 1 2.5 0v7.5a1.25 1.25 0 1 1-2.5 0v-7.5ZM11 3V1.7c0-.268.14-.526.395-.607A2 2 0 0 1 14 3c0 .995-.182 1.948-.514 2.826-.204.54.166 1.174.744 1.174h2.52c1.243 0 2.261 1.01 2.261 2.251v5.753c0 1.24-1.018 2.251-2.261 2.251h-6.83a2 2 0 0 1-1.396-.519l-3.674-2.25a1.25 1.25 0 0 1 .6 2.05l-3.33 2.155a.75.75 0 0 1-1.16-.628l-.34-4.86A3.251 3.251 0 0 1 5 6.75h1.25v2.247l3.655-2.274a2 2 0 0 1 1.345-.523h4.636l-1.03-3.07a.75.75 0 0 0-.712-.511L11 3Z" />
                            </svg>
                        </div>
                    ) : (
                        <div className="bg-red-100 text-red-700 p-1 rounded-full shadow-sm">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3 h-3">
                                <path d="M18.905 12.75a1.25 1.25 0 0 1-2.5 0v-7.5a1.25 1.25 0 1 1 2.5 0v7.5ZM8.905 17v1.3c0 .268-.14.526-.395.607A2 2 0 0 1 5.905 17c0-.995.182-1.948.514-2.826.204-.54-.166-1.174-.744-1.174h-2.52c-1.243 0-2.261-1.01-2.261-2.251v-5.753c0-1.24 1.018-2.251 2.261-2.251h6.83A2 2 0 0 1 11.381 3.26l3.674 2.25a1.25 1.25 0 0 1-.6-2.05l3.33-2.155a.75.75 0 0 1 1.16.628l.34 4.86a3.251 3.251 0 0 1-1.924 3.957h-1.25v-2.247l-3.655 2.274a2 2 0 0 1-1.345.523h-4.636l1.03 3.07a.75.75 0 0 0 .712.511l.104-.005Z" />
                            </svg>
                        </div>
                    )}
                </div>
            )}

            <p className="text-xs text-slate-500 mt-1 line-clamp-2">
                {scene.purpose}
            </p>
        </button>
    );
}

interface SceneModalProps {
    scenes: StoryboardScene[];
    currentIndex: number;
    onClose: () => void;
    onNavigate: (index: number) => void;
    feedbackMap: Record<string, Feedback>;
    onFeedbackUpdate: (feedback: Feedback) => void;
}

function SceneModal({ scenes, currentIndex, onClose, onNavigate, feedbackMap, onFeedbackUpdate }: SceneModalProps) {
    const { session, setScenes, sendMessage } = useSessionStore();
    const scene = scenes[currentIndex];
    const sceneMatchLabel = getSceneMatchLabel(scene);
    const isGenerated = sceneMatchLabel === 'Generated';
    const canGoPrev = currentIndex > 0;
    const canGoNext = currentIndex < scenes.length - 1;

    const [isEditing, setIsEditing] = useState(false);
    const [editedScene, setEditedScene] = useState<StoryboardScene>(scene);
    const [isSaving, setIsSaving] = useState(false);

    useEffect(() => {
        setEditedScene(scene);
    }, [scene]);

    // Handle click outside to close
    const handleBackdropClick = useCallback((e: React.MouseEvent) => {
        if (e.target === e.currentTarget) {
            onClose();
        }
    }, [onClose]);

    const getSceneChanges = (original: StoryboardScene, updated: StoryboardScene): string[] => {
        const changes: string[] = [];
        if (original.title !== updated.title) {
            changes.push(`Changed title from "${original.title}" to "${updated.title}"`);
        }
        if (original.purpose !== updated.purpose) {
            changes.push(`Changed purpose to: "${updated.purpose}"`);
        }
        if (original.script !== updated.script) {
            changes.push(`Changed script to: "${updated.script}"`);
        }
        return changes;
    };

    const handleSave = async (notifyAgent: boolean = false) => {
        if (!session) return;
        setIsSaving(true);
        try {
            const updatedScenes = [...scenes];
            updatedScenes[currentIndex] = editedScene;

            await api.updateStoryboard(session.id, updatedScenes);
            setScenes(updatedScenes);

            // Close the edit mode immediately so the user can continue
            setIsEditing(false);

            if (notifyAgent) {
                const changes = getSceneChanges(scene, editedScene);
                if (changes.length > 0) {
                    const message = `I updated Scene ${currentIndex + 1} (${editedScene.title}):\n- ${changes.join('\n- ')}`;
                    // Fire and forget, don't await the message sending
                    sendMessage(message).catch(err => console.error('Failed to notify agent:', err));
                }
                // Close the modal completely when notifying
                onClose();
            }
        } catch (error) {
            console.error('Failed to update storyboard:', error);
            // Optionally add toast here
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
            onClick={handleBackdropClick}
        >
            <div className="relative bg-white rounded-2xl shadow-2xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-hidden flex flex-col">
                {/* Header */}
                <div className="px-6 py-4 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <span className="text-sm text-slate-500 font-mono">
                            Scene {currentIndex + 1} of {scenes.length}
                        </span>
                        {scene.matched_scene && (
                            <span
                                className={`text-xs px-2 py-1 rounded ${isGenerated
                                    ? 'bg-cyan-100 text-cyan-700'
                                    : 'bg-green-100 text-green-700'
                                    }`}
                            >
                                {sceneMatchLabel}
                            </span>
                        )}
                    </div>

                    <div className="flex items-center gap-2">
                        {!isEditing && (
                            <button
                                onClick={() => setIsEditing(true)}
                                className="p-2 hover:bg-slate-200 rounded-lg transition-colors text-slate-500 hover:text-teal-600"
                                title="Edit Scene"
                            >
                                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                                    <path d="M5.433 13.917l1.262-3.155A4 4 0 017.58 9.42l6.92-6.918a2.121 2.121 0 013 3l-6.92 6.918c-.383.383-.84.685-1.343.886l-3.154 1.262a.5.5 0 01-.65-.65z" />
                                    <path d="M3.5 5.75c0-.69.56-1.25 1.25-1.25H10A.75.75 0 0010 3H4.75A2.75 2.75 0 002 5.75v9.5A2.75 2.75 0 004.75 18h9.5A2.75 2.75 0 0017 15.25V10a.75.75 0 00-1.5 0v5.25c0 .69-.56 1.25-1.25 1.25h-9.5c-.69 0-1.25-.56-1.25-1.25v-9.5z" />
                                </svg>
                            </button>
                        )}
                        <button
                            onClick={onClose}
                            className="p-2 hover:bg-slate-200 rounded-lg transition-colors"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5 text-slate-500">
                                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                            </svg>
                        </button>
                    </div>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-6 pb-16 space-y-4 relative">
                    {isEditing ? (
                        <div className="space-y-4">
                            <div>
                                <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">Title</label>
                                <input
                                    type="text"
                                    className="w-full text-lg font-semibold text-slate-800 p-2 border border-slate-200 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none"
                                    value={editedScene.title}
                                    onChange={e => setEditedScene({ ...editedScene, title: e.target.value })}
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">Purpose</label>
                                <textarea
                                    className="w-full text-sm text-slate-700 p-3 border border-slate-200 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none min-h-[80px]"
                                    value={editedScene.purpose}
                                    onChange={e => setEditedScene({ ...editedScene, purpose: e.target.value })}
                                />
                            </div>

                            <div>
                                <label className="block text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">Voice Over Script</label>
                                <textarea
                                    className="w-full text-sm text-slate-600 italic bg-slate-50 p-3 border border-slate-200 rounded-lg focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none min-h-[100px]"
                                    value={editedScene.script}
                                    onChange={e => setEditedScene({ ...editedScene, script: e.target.value })}
                                />
                            </div>

                            <div className="flex gap-2 justify-end pt-4">
                                <button
                                    onClick={() => {
                                        setIsEditing(false);
                                        setEditedScene(scene);
                                    }}
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
                            <h3 className="text-xl font-semibold text-slate-800">{scene.title}</h3>

                            <div>
                                <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
                                    Purpose
                                </p>
                                <p className="text-sm text-slate-700">{scene.purpose}</p>
                            </div>

                            {scene.script && (
                                <div>
                                    <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
                                        Voice Over Script
                                    </p>
                                    <p className="text-sm text-slate-600 italic bg-slate-50 p-3 rounded-lg border border-slate-100">
                                        &quot;{scene.script}&quot;
                                    </p>
                                </div>
                            )}

                            {scene.matched_scene && (
                                <div className={`rounded-lg p-4 border ${isGenerated
                                    ? 'bg-cyan-50 border-cyan-100'
                                    : 'bg-green-50 border-green-100'
                                    }`}>
                                    <p className={`text-xs font-medium uppercase tracking-wide mb-2 ${isGenerated
                                        ? 'text-cyan-700'
                                        : 'text-green-700'
                                        }`}>
                                        {sceneMatchLabel} Clip
                                    </p>
                                    <div className={`space-y-1 text-sm ${isGenerated
                                        ? 'text-cyan-800'
                                        : 'text-green-800'
                                        }`}>
                                        <p>
                                            <span className={isGenerated ? 'text-cyan-600' : 'text-green-600'}>Source:</span>{' '}
                                            {formatMatchedSource(scene.matched_scene.source_video_id)}
                                        </p>
                                        <p>
                                            <span className={isGenerated ? 'text-cyan-600' : 'text-green-600'}>Range:</span>{' '}
                                            {scene.matched_scene.start_time.toFixed(1)}s - {scene.matched_scene.end_time.toFixed(1)}s
                                        </p>
                                        {scene.matched_scene.description && (
                                            <p>
                                                <span className={isGenerated ? 'text-cyan-600' : 'text-green-600'}>Description:</span>{' '}
                                                {scene.matched_scene.description}
                                            </p>
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* Candidate Selection Pills */}
                            {scene.matched_scene_candidates && scene.matched_scene_candidates.length > 1 && (
                                <div className="bg-slate-50 rounded-lg p-4 border border-slate-200">
                                    <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-3">
                                        Alternative Candidates
                                    </p>
                                    <div className="flex flex-wrap gap-2">
                                        {scene.matched_scene_candidates.map((candidate, idx) => {
                                            const isSelected = scene.selected_candidate_id === candidate.candidate_id;
                                            return (
                                                <button
                                                    key={candidate.candidate_id}
                                                    onClick={async () => {
                                                        if (isSelected || !session) return;
                                                        try {
                                                            const updatedScene = await api.selectCandidate(
                                                                session.id,
                                                                scene.scene_id,
                                                                candidate.candidate_id,
                                                                'User selected via UI'
                                                            );
                                                            // Update scenes in store
                                                            const newScenes = [...scenes];
                                                            newScenes[currentIndex] = updatedScene;
                                                            setScenes(newScenes);
                                                        } catch (error) {
                                                            console.error('Failed to select candidate:', error);
                                                        }
                                                    }}
                                                    className={`px-3 py-1.5 text-xs font-medium rounded-full transition-all ${isSelected
                                                        ? 'bg-teal-600 text-white shadow-sm'
                                                        : 'bg-white text-slate-600 border border-slate-300 hover:border-teal-400 hover:text-teal-600'
                                                        }`}
                                                    title={candidate.description || `Candidate ${idx + 1}`}
                                                >
                                                    {isSelected && (
                                                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3 inline mr-1">
                                                            <path fillRule="evenodd" d="M12.416 3.376a.75.75 0 0 1 .208 1.04l-5 7.5a.75.75 0 0 1-1.154.114l-3-3a.75.75 0 0 1 1.06-1.06l2.353 2.353 4.493-6.739a.75.75 0 0 1 1.04-.208Z" clipRule="evenodd" />
                                                        </svg>
                                                    )}
                                                    Option {idx + 1}
                                                </button>
                                            );
                                        })}
                                    </div>
                                    {scene.selected_candidate_id && (
                                        <p className="text-xs text-slate-400 mt-2">
                                            Click a pill to switch clips
                                        </p>
                                    )}
                                </div>
                            )}

                            {/* Feedback Control in Modal - Sleek */}
                            {session && (
                                <div className="absolute bottom-4 right-4 z-10">
                                    <FeedbackControl
                                        sessionId={session.id}
                                        targetType="scene"
                                        targetId={scene.scene_id}
                                        initialFeedback={feedbackMap[`scene:${scene.scene_id}`] || null}
                                        onFeedbackUpdate={onFeedbackUpdate}
                                        variant="minimal"
                                    />
                                </div>
                            )}
                        </>
                    )}
                </div>

                {/* Navigation Footer - Only show when not editing */}
                {!isEditing && (
                    <div className="px-6 py-4 border-t border-slate-200 bg-slate-50 flex items-center justify-between">
                        <button
                            onClick={() => onNavigate(currentIndex - 1)}
                            disabled={!canGoPrev}
                            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-700 
                                    hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                                <path fillRule="evenodd" d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z" clipRule="evenodd" />
                            </svg>
                            Previous
                        </button>

                        <div className="flex gap-1">
                            {scenes.map((_, idx) => (
                                <button
                                    key={idx}
                                    onClick={() => onNavigate(idx)}
                                    className={`w-2 h-2 rounded-full transition-colors ${idx === currentIndex ? 'bg-teal-500' : 'bg-slate-300 hover:bg-slate-400'
                                        }`}
                                />
                            ))}
                        </div>

                        <button
                            onClick={() => onNavigate(currentIndex + 1)}
                            disabled={!canGoNext}
                            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-700 
                                    hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                            Next
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                                <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
                            </svg>
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
