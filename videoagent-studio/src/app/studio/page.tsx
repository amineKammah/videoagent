'use client';

import { Chat } from '@/components/chat';
import { Sidebar } from '@/components/Sidebar';
import { ProjectBrief } from '@/components/ProjectBrief';
import { Storyboard } from '@/components/Storyboard';
import { VideoPlayer } from '@/components/VideoPlayer';

export default function StudioPage() {
    return (
        <div className="flex h-screen bg-slate-50">
            {/* Sidebar */}
            <Sidebar />

            {/* Main Content */}
            <main className="flex-1 flex flex-col p-6 overflow-hidden">
                {/* Header */}
                <div className="mb-6">
                    <h1 className="text-2xl font-bold text-slate-800 font-serif">
                        VideoAgent Studio
                    </h1>
                    <p className="text-slate-500 mt-1">
                        Chat, craft the storyboard, match footage, and render a polished sales video.
                    </p>
                </div>

                {/* Content Grid */}
                <div className="flex-1 grid grid-cols-4 gap-6 min-h-0">
                    {/* Chat Panel */}
                    <div className="col-span-1 min-h-0">
                        <Chat />
                    </div>

                    {/* Right Panel - Brief + Storyboard + Video */}
                    <div className="col-span-3 min-h-0 flex flex-col gap-4 overflow-y-auto">
                        {/* Project Brief - Collapsible */}
                        <ProjectBrief />

                        {/* Video Player */}
                        <VideoPlayer />

                        {/* Storyboard */}
                        <div className="flex-1 bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden flex flex-col min-h-[300px]">
                            <div className="px-4 py-3 border-b border-slate-200 bg-slate-50">
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
