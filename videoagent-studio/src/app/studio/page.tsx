'use client';

import { Suspense } from 'react';

import { Chat } from '@/components/chat';
import { Sidebar } from '@/components/Sidebar';
import { RightSidebar } from '@/components/RightSidebar';
import { ProjectBrief } from '@/components/ProjectBrief';
import { Storyboard } from '@/components/Storyboard';
import { VideoPlayer } from '@/components/VideoPlayer';
import { VideoStatus } from '@/components/VideoStatus';
import { useSessionStore } from '@/store/session';
import { getVideoPreviewState } from '@/lib/videoPreviewState';

export default function StudioPage() {
    const isProcessing = useSessionStore(state => state.isProcessing);
    const videoGenerating = useSessionStore(state => state.videoGenerating);
    const scenes = useSessionStore(state => state.scenes);
    const hasScenes = scenes.length > 0;
    const allScenesReady = hasScenes && scenes.every(scene => Boolean(scene.matched_scene));
    const previewState = getVideoPreviewState({
        hasScenes,
        allScenesReady,
        isProcessing,
        videoGenerating,
    });

    return (
        <div className="flex h-[calc(100vh-4rem)] bg-slate-50">
            {/* Sidebar */}
            <Suspense fallback={<div className="w-64 bg-white border-r border-slate-200" />}>
                <Sidebar />
            </Suspense>

            <RightSidebar />

            {/* Main Content */}
            <main className="flex-1 flex flex-col p-3 overflow-hidden mr-10">


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
                        {previewState !== 'hidden' && (
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
                                    {previewState === 'loading' && (
                                        <VideoStatus />
                                    )}

                                    {previewState === 'ready' && (
                                        <VideoPlayer />
                                    )}

                                    {previewState === 'incomplete' && (
                                        <div className="h-full w-full flex flex-col items-center justify-center text-slate-500 p-8">
                                            <div className="w-14 h-14 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center mb-4">
                                                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-7 h-7">
                                                    <path fillRule="evenodd" d="M9.401 3.003c1.155-2 4.043-2 5.198 0l7.355 12.741c1.154 2-.29 4.5-2.599 4.5H4.645c-2.309 0-3.753-2.5-2.599-4.5L9.4 3.003zM12 8.25a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0V9a.75.75 0 01.75-.75zm0 8.25a1.125 1.125 0 100-2.25 1.125 1.125 0 000 2.25z" clipRule="evenodd" />
                                                </svg>
                                            </div>
                                            <p className="text-sm font-medium text-slate-700 text-center">Video preview is waiting for missing scenes</p>
                                            <p className="text-xs text-slate-400 mt-1 text-center max-w-md">
                                                Some storyboard scenes still do not have selected clips. Ask the agent to continue matching or generate the remaining scenes.
                                            </p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* Storyboard */}
                        <div className="w-full bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col shrink-0 transition-all duration-300">
                            <div className="px-4 py-2 border-b border-slate-200 bg-slate-50">
                                <h2 className="font-semibold text-slate-800">Storyboard</h2>
                                <p className="text-xs text-slate-500">Scenes and selected video clips</p>
                            </div>

                            <Storyboard />
                        </div>

                    </div>
                </div>
            </main>
        </div>

    );
}
