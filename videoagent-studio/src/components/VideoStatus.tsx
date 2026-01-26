'use client';

import { useState } from 'react';
import { useSessionStore } from '@/store/session';

export function VideoStatus() {
    const videoGenerating = useSessionStore(state => state.videoGenerating);
    const videoPath = useSessionStore(state => state.videoPath);
    const [showPlayer, setShowPlayer] = useState(false);

    // Don't show anything if no video activity
    if (!videoGenerating && !videoPath) {
        return null;
    }

    return (
        <div className="h-full w-full flex flex-col">
            {/* Generating state */}
            {videoGenerating && (
                <div className="flex-1 flex flex-col items-center justify-center text-slate-500 p-8">
                    <div className="relative w-16 h-16 mb-4">
                        <div className="absolute inset-0 border-4 border-slate-200 rounded-full" />
                        <div className="absolute inset-0 border-4 border-teal-500 rounded-full border-t-transparent animate-spin" />
                        <div className="absolute inset-0 flex items-center justify-center">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-6 h-6 text-teal-600">
                                <path fillRule="evenodd" d="M4.5 5.653c0-1.426 1.529-2.33 2.779-1.643l11.54 6.348c1.295.712 1.295 2.573 0 3.285L7.28 19.991c-1.25.687-2.779-.217-2.779-1.643V5.653z" clipRule="evenodd" />
                            </svg>
                        </div>
                    </div>
                    <p className="text-sm font-medium text-slate-700">Generating video...</p>
                    <p className="text-xs text-slate-400 mt-1">This may take a few minutes</p>
                </div>
            )}

            {/* Video player */}
            {!videoGenerating && videoPath && (
                <div className="p-4 flex-1 flex flex-col">
                    <video
                        key={videoPath}
                        controls
                        className="w-full rounded-lg bg-black max-h-[600px] object-contain"
                        src={videoPath.startsWith('/') ? `file://${videoPath}` : videoPath}
                    >
                        Your browser does not support the video tag.
                    </video>
                    <p className="text-xs text-slate-400 mt-2 truncate" title={videoPath}>
                        {videoPath}
                    </p>
                </div>
            )}
        </div>
    );
}
