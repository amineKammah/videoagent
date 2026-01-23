import { useState, useEffect, useRef, useCallback } from 'react';

interface ClipTrimmerProps {
    duration: number; // Total duration of the source video in seconds
    startTime: number; // Current start time in seconds
    endTime: number; // Current end time in seconds
    voDuration?: number; // Duration of the voice over in seconds (if any)
    onChange: (start: number, end: number) => void;
    onPreview: () => void;
    isPreviewing: boolean;
}

export function ClipTrimmer({
    duration,
    startTime,
    endTime,
    voDuration,
    onChange,
    onPreview,
    isPreviewing,
}: ClipTrimmerProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [isDragging, setIsDragging] = useState<'start' | 'end' | null>(null);

    // Constraint calculation
    const minDuration = voDuration ? voDuration * 0.9 : 0.5; // Min 0.5s or 90% of VO
    const maxDuration = voDuration ? voDuration * 1.1 : duration; // Max duration or 110% of VO

    const formatTime = (time: number) => {
        const minutes = Math.floor(time / 60);
        const seconds = Math.floor(time % 60);
        const millis = Math.floor((time % 1) * 10);
        return `${minutes}:${seconds.toString().padStart(2, '0')}.${millis}`;
    };

    const getPercentage = (time: number) => (time / duration) * 100;

    const handleMouseDown = (type: 'start' | 'end') => (e: React.MouseEvent) => {
        setIsDragging(type);
        e.preventDefault();
    };

    const handleMouseMove = useCallback(
        (e: MouseEvent) => {
            if (!isDragging || !containerRef.current) return;

            const rect = containerRef.current.getBoundingClientRect();
            const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
            const percentage = x / rect.width;
            let newTime = percentage * duration;

            if (isDragging === 'start') {
                // Constraints for start handle
                // 1. Must be >= 0
                newTime = Math.max(0, newTime);
                // 2. Must be < endTime - minDuration
                newTime = Math.min(newTime, endTime - minDuration);

                // VO Constraint: Segment duration check
                // current segment duration = endTime - newTime
                if (voDuration) {
                    // if duration is too long > maxDuration
                    if ((endTime - newTime) > maxDuration) {
                        newTime = endTime - maxDuration;
                    }
                }

                onChange(newTime, endTime);
            } else {
                // Constraints for end handle
                // 1. Must be <= duration
                newTime = Math.min(duration, newTime);
                // 2. Must be > startTime + minDuration
                newTime = Math.max(newTime, startTime + minDuration);

                // VO Constraint
                if (voDuration) {
                    if ((newTime - startTime) > maxDuration) {
                        newTime = startTime + maxDuration;
                    }
                }

                onChange(startTime, newTime);
            }
        },
        [isDragging, duration, startTime, endTime, minDuration, onChange, voDuration, maxDuration]
    );

    const handleMouseUp = useCallback(() => {
        setIsDragging(null);
    }, []);

    useEffect(() => {
        if (isDragging) {
            window.addEventListener('mousemove', handleMouseMove);
            window.addEventListener('mouseup', handleMouseUp);
        }
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isDragging, handleMouseMove, handleMouseUp]);

    // Safe zone calculation for visualization
    const safeZoneStart = voDuration ? Math.max(0, (startTime + endTime - maxDuration) / 2) : 0; // Rough approximation for visualization

    return (
        <div className="bg-slate-900 rounded-lg p-4 select-none">
            <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-mono text-slate-400">
                    Total: {formatTime(duration)}
                </span>
                <div className="flex gap-4">
                    {voDuration && (
                        <span className="text-xs text-amber-500 font-medium flex items-center gap-1">
                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"></path></svg>
                            VO Locked ({formatTime(endTime - startTime)})
                        </span>
                    )}
                    <span className="text-xs font-mono text-teal-400">
                        Selected: {formatTime(startTime)} - {formatTime(endTime)} ({formatTime(endTime - startTime)})
                    </span>
                </div>
            </div>

            <div className="relative h-12 flex items-center" ref={containerRef}>
                {/* Background Track */}
                <div className="absolute w-full h-2 bg-slate-700 rounded-full overflow-hidden">
                    {/* Optional Safe Zone Visuals could go here */}
                </div>

                {/* Selected Range */}
                <div
                    className="absolute h-2 bg-teal-600/50"
                    style={{
                        left: `${getPercentage(startTime)}%`,
                        width: `${getPercentage(endTime - startTime)}%`,
                    }}
                />

                {/* Start Handle */}
                <div
                    className="absolute h-6 w-4 bg-teal-500 rounded cursor-ew-resize z-10 hover:bg-teal-400 flex items-center justify-center group"
                    style={{ left: `${getPercentage(startTime)}%`, transform: 'translateX(-50%)' }}
                    onMouseDown={handleMouseDown('start')}
                >
                    <div className="w-0.5 h-3 bg-teal-900/30"></div>
                    {/* Tooltip */}
                    <div className="absolute bottom-full mb-2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-800 text-white text-xs py-1 px-2 rounded whitespace-nowrap pointer-events-none">
                        {formatTime(startTime)}
                    </div>
                </div>

                {/* End Handle */}
                <div
                    className="absolute h-6 w-4 bg-teal-500 rounded cursor-ew-resize z-10 hover:bg-teal-400 flex items-center justify-center group"
                    style={{ left: `${getPercentage(endTime)}%`, transform: 'translateX(-50%)' }}
                    onMouseDown={handleMouseDown('end')}
                >
                    <div className="w-0.5 h-3 bg-teal-900/30"></div>
                    {/* Tooltip */}
                    <div className="absolute bottom-full mb-2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-800 text-white text-xs py-1 px-2 rounded whitespace-nowrap pointer-events-none">
                        {formatTime(endTime)}
                    </div>
                </div>
            </div>

            <div className="mt-2 flex justify-center">
                <button
                    onClick={onPreview}
                    className={`flex items-center gap-2 px-3 py-1.5 rounded text-xs font-medium transition-colors
            ${isPreviewing
                            ? 'bg-amber-600 text-white hover:bg-amber-700'
                            : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                        }`}
                >
                    {isPreviewing ? (
                        <>
                            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" /></svg>
                            Stop Preview
                        </>
                    ) : (
                        <>
                            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
                            Preview Clip Loop
                        </>
                    )}
                </button>
            </div>
        </div>
    );
}
