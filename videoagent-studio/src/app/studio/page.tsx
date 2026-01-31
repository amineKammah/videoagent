'use client';

import { Suspense } from 'react';

import { Chat } from '@/components/chat';
import { Sidebar } from '@/components/Sidebar';
import { ProjectBrief } from '@/components/ProjectBrief';
import { Storyboard } from '@/components/Storyboard';
import { VideoPlayer } from '@/components/VideoPlayer';
import { VideoStatus } from '@/components/VideoStatus';
import { useSessionStore } from '@/store/session';

export default function StudioPage() {
    const videoGenerating = useSessionStore(state => state.videoGenerating);
    const scenes = useSessionStore(state => state.scenes);
    const hasMatchedScenes = scenes.some(s => s.matched_scene);
    const showVideo = videoGenerating || hasMatchedScenes;
    return (
        <div className="flex h-[calc(100vh-4rem)] bg-slate-50">
            {/* Sidebar */}
            <Suspense fallback={<div className="w-64 bg-white border-r border-slate-200" />}>
                <Sidebar />
            </Suspense>

            {/* Main Content */}
            <main className="flex-1 flex flex-col p-3 overflow-hidden">


                {/* Content Grid */}
                <div className="flex-1 grid grid-cols-4 gap-6 min-h-0">
                    {/* Chat Panel */}
                    <div className="col-span-1 min-h-0 flex flex-col">
                        <div className="mb-4">
                            <h1 className="text-xl font-bold text-slate-800 font-serif">VideoAgent Studio</h1>
                        </div>
                        <Suspense fallback={<div className="flex-1 bg-white rounded-xl border border-slate-200" />}>
                            <Chat />
                        </Suspense>
                    </div>

                    {/* Right Panel - Brief + Storyboard + Video */}
                    <div className="col-span-3 min-h-0 flex flex-col gap-6 overflow-y-auto pr-2 custom-scrollbar">
                        {/* Project Brief - Collapsible */}
                        <ProjectBrief />

                        {/* Video Player Section */}
                        {(videoGenerating || hasMatchedScenes) && (
                            <div className="w-full bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col shrink-0">
                                {/* Video Header */}
                                <div className="px-4 py-2 border-b border-slate-200 bg-slate-50 flex justify-between items-center">
                                    <div>
                                        <h3 className="font-semibold text-slate-800">Video Preview</h3>
                                        <p className="text-xs text-slate-500">Real-time composition</p>
                                    </div>
                                </div>

                                {/* Content */}
                                <div className="flex-1 relative min-h-0">
                                    {videoGenerating && !hasMatchedScenes ? (
                                        <VideoStatus />
                                    ) : (
                                        <VideoPlayer />
                                    )}
                                </div>
                            </div>
                        )}

                        {/* Storyboard */}
                        <div className="w-full bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col shrink-0 transition-all duration-300">
                            <div className="px-4 py-2 border-b border-slate-200 bg-slate-50">
                                <h2 className="font-semibold text-slate-800">Storyboard</h2>
                                <p className="text-xs text-slate-500">Scenes and matched video clips</p>
                            </div>

                            <Storyboard />
                        </div>

                    </div>
                </div>
            </main>
        </div>

    );
}
