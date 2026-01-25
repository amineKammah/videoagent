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
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <h2 className="font-semibold text-slate-800">Video</h2>
                    {videoGenerating && (
                        <span className="text-xs bg-amber-100 text-amber-700 px-2 py-1 rounded-full flex items-center gap-1">
                            <span className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
                            Generating...
                        </span>
                    )}
                    {!videoGenerating && videoPath && (
                        <span className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded-full flex items-center gap-1">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3 h-3">
                                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd" />
                            </svg>
                            Ready
                        </span>
                    )}
                </div>
                {!videoGenerating && videoPath && (
                    <button
                        onClick={() => setShowPlayer(!showPlayer)}
                        className="text-sm text-teal-600 hover:text-teal-700 font-medium flex items-center gap-1"
                    >
                        {showPlayer ? (
                            <>
                                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                                    <path fillRule="evenodd" d="M14.77 12.79a.75.75 0 01-1.06-.02L10 8.832l-3.71 3.938a.75.75 0 11-1.08-1.04l4.25-4.5a.75.75 0 011.08 0l4.25 4.5a.75.75 0 01-.02 1.06z" clipRule="evenodd" />
                                </svg>
                                Hide
                            </>
                        ) : (
                            <>
                                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
                                    <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
                                </svg>
                                Watch
                            </>
                        )}
                    </button>
                )}
            </div>

            {/* Generating state */}
            {videoGenerating && (
                <div className="p-8 flex flex-col items-center justify-center text-slate-500">
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
            {!videoGenerating && videoPath && showPlayer && (
                <div className="p-4">
                    <video
                        key={videoPath}
                        controls
                        className="w-full rounded-lg bg-black"
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
