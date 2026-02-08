'use client';

import { useSessionStore } from '@/store/session';

export function VideoStatus() {
    const isProcessing = useSessionStore(state => state.isProcessing);
    const videoGenerating = useSessionStore(state => state.videoGenerating);

    if (!isProcessing && !videoGenerating) {
        return null;
    }

    const title = videoGenerating ? 'Generating video...' : 'Preparing video preview...';
    const subtitle = videoGenerating
        ? 'Matching and generating scenes in the background'
        : 'Applying the latest storyboard updates';

    return (
        <div className="h-full w-full flex flex-col">
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
                <p className="text-sm font-medium text-slate-700">{title}</p>
                <p className="text-xs text-slate-400 mt-1">{subtitle}</p>
            </div>
        </div>
    );
}
