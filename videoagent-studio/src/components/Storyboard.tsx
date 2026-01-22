'use client';

import { useState } from 'react';
import { useSessionStore } from '@/store/session';
import { StoryboardScene } from '@/lib/types';

export function Storyboard() {
    const scenes = useSessionStore(state => state.scenes);

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
        <div className="flex-1 overflow-y-auto p-4">
            <div className="space-y-2">
                {scenes.map((scene, index) => (
                    <SceneCard key={scene.scene_id} scene={scene} index={index} />
                ))}
            </div>
        </div>
    );
}

function SceneCard({ scene, index }: { scene: StoryboardScene; index: number }) {
    const [isExpanded, setIsExpanded] = useState(false);

    return (
        <div className="bg-slate-50 rounded-lg border border-slate-200 overflow-hidden">
            {/* Header - Always visible, clickable to expand */}
            <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-100 transition-colors text-left"
            >
                <div className="flex items-center gap-3">
                    <span className="text-xs text-slate-400 font-mono w-16">
                        Scene {index + 1}
                    </span>
                    <h4 className="font-medium text-slate-800">{scene.title}</h4>
                </div>
                <div className="flex items-center gap-2">
                    {scene.matched_scene && (
                        <span className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded">
                            Matched
                        </span>
                    )}
                    <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 20 20"
                        fill="currentColor"
                        className={`w-4 h-4 text-slate-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                    >
                        <path
                            fillRule="evenodd"
                            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                            clipRule="evenodd"
                        />
                    </svg>
                </div>
            </button>

            {/* Expanded content */}
            {isExpanded && (
                <div className="px-4 pb-4 border-t border-slate-200">
                    <div className="pt-3 space-y-3">
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
                                <p className="text-sm text-slate-600 italic">"{scene.script}"</p>
                            </div>
                        )}

                        {scene.matched_scene && (
                            <div className="bg-green-50 rounded-lg p-3 border border-green-100">
                                <p className="text-xs font-medium text-green-700 uppercase tracking-wide mb-2">
                                    Matched Clip
                                </p>
                                <div className="space-y-1 text-sm text-green-800">
                                    <p><span className="text-green-600">Source:</span> {scene.matched_scene.source_video_id}</p>
                                    <p>
                                        <span className="text-green-600">Range:</span>{' '}
                                        {scene.matched_scene.start_time.toFixed(1)}s - {scene.matched_scene.end_time.toFixed(1)}s
                                    </p>
                                    {scene.matched_scene.description && (
                                        <p><span className="text-green-600">Description:</span> {scene.matched_scene.description}</p>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
