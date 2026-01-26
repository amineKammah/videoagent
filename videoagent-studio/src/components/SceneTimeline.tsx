'use client';

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { StoryboardScene, VideoMetadata } from '@/lib/types';

interface SceneTimelineProps {
    scenes: StoryboardScene[];
    metadata: Record<string, VideoMetadata>;
    currentSceneIndex: number;
    onSceneSelect: (index: number) => void;
    onTrimChange: (start: number, end: number, handle: 'start' | 'end') => void;
    onTrimEnd?: (start: number, end: number) => void;
    isPlaying: boolean;
}

interface SceneSegment {
    index: number;
    scene: StoryboardScene;
    startOffset: number; // cumulative offset from beginning
    duration: number;
}

export function SceneTimeline({
    scenes,
    metadata,
    currentSceneIndex,
    onSceneSelect,
    onTrimChange,
    onTrimEnd,
    isPlaying,
}: SceneTimelineProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
    const [isDragging, setIsDragging] = useState<'start' | 'end' | null>(null);
    const lastTrimRef = useRef<{ start: number; end: number } | null>(null);

    // Calculate segments with their positions
    const { segments, totalDuration } = useMemo(() => {
        let offset = 0;
        const segs: SceneSegment[] = [];

        scenes.forEach((scene, index) => {
            let duration = 0;
            if (scene.matched_scene) {
                duration = scene.matched_scene.end_time - scene.matched_scene.start_time;
            }
            segs.push({
                index,
                scene,
                startOffset: offset,
                duration,
            });
            offset += duration;
        });

        return { segments: segs, totalDuration: offset };
    }, [scenes]);

    // Current scene info
    const activeScene = scenes[currentSceneIndex];
    const activeMetadata = activeScene?.matched_scene
        ? metadata[activeScene.matched_scene.source_video_id]
        : null;

    // Trim constraints (from ClipTrimmer)
    const voDuration = activeScene?.use_voice_over && activeScene?.voice_over
        ? activeScene.voice_over.duration
        : undefined;
    const minDuration = voDuration ? voDuration * 0.9 : 0.5;
    const maxDuration = voDuration ? voDuration * 1.1 : (activeMetadata?.duration ?? 1000);

    // Calculate percentage position
    const getPercentage = (time: number) => totalDuration > 0 ? (time / totalDuration) * 100 : 0;

    // Handle trim dragging
    const handleMouseDown = (type: 'start' | 'end') => (e: React.MouseEvent) => {
        e.stopPropagation();
        setIsDragging(type);
        lastTrimRef.current = null; // Reset on start
    };

    const handleMouseMove = useCallback(
        (e: MouseEvent) => {
            if (!isDragging || !containerRef.current || !activeScene?.matched_scene || !activeMetadata) return;

            const rect = containerRef.current.getBoundingClientRect();
            const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
            const percentage = x / rect.width;

            // Convert to time within the composition
            const compositionTime = percentage * totalDuration;

            // Find the current segment
            const currentSegment = segments[currentSceneIndex];
            if (!currentSegment) return;

            // Convert to time within the source video
            const segmentStart = currentSegment.startOffset;
            const relativeTime = compositionTime - segmentStart;

            // Map relative time back to source video times
            const sourceStartTime = activeScene.matched_scene.start_time;
            const sourceEndTime = activeScene.matched_scene.end_time;

            let newStart = sourceStartTime;
            let newEnd = sourceEndTime;

            if (isDragging === 'start') {
                // Adjust start time
                newStart = sourceStartTime + relativeTime;

                // Constraints
                newStart = Math.max(0, newStart);
                newStart = Math.min(newStart, sourceEndTime - minDuration);

                if (voDuration && (sourceEndTime - newStart) > maxDuration) {
                    newStart = sourceEndTime - maxDuration;
                }
            } else {
                // Adjust end time
                const currentDuration = sourceEndTime - sourceStartTime;
                newEnd = sourceStartTime + relativeTime;

                // Constraints
                newEnd = Math.min(activeMetadata.duration, newEnd);
                newEnd = Math.max(newEnd, sourceStartTime + minDuration);

                if (voDuration && (newEnd - sourceStartTime) > maxDuration) {
                    newEnd = sourceStartTime + maxDuration;
                }
            }

            // Update ref
            lastTrimRef.current = { start: newStart, end: newEnd };

            // Notify parent
            onTrimChange(newStart, newEnd, isDragging);
        },
        [isDragging, totalDuration, segments, currentSceneIndex, activeScene, activeMetadata, minDuration, maxDuration, voDuration, onTrimChange]
    );

    const handleMouseUp = useCallback(() => {
        if (isDragging && lastTrimRef.current && onTrimEnd) {
            onTrimEnd(lastTrimRef.current.start, lastTrimRef.current.end);
        }
        setIsDragging(null);
        lastTrimRef.current = null;
    }, [isDragging, onTrimEnd]);

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

    const formatTime = (time: number) => {
        const minutes = Math.floor(time / 60);
        const seconds = Math.floor(time % 60);
        const millis = Math.floor((time % 1) * 10);
        return `${minutes}:${seconds.toString().padStart(2, '0')}.${millis}`;
    };

    if (totalDuration === 0) return null;

    return (
        <div className="mt-4 px-4 select-none">


            {/* Timeline container */}
            <div
                ref={containerRef}
                className="relative h-8 w-full"
            >
                {segments.map((segment) => {
                    const isActive = segment.index === currentSceneIndex;
                    const isHovered = segment.index === hoveredIndex;
                    const left = getPercentage(segment.startOffset);
                    const width = getPercentage(segment.duration);

                    if (segment.duration === 0) return null;

                    return (
                        <div
                            key={segment.scene.scene_id}
                            className="absolute group"
                            style={{
                                left: `${left}%`,
                                width: `calc(${width}% - 2px)`, // 2px gap between segments
                                marginLeft: segment.index > 0 ? '2px' : '0',
                            }}
                            onMouseEnter={() => setHoveredIndex(segment.index)}
                            onMouseLeave={() => setHoveredIndex(null)}
                            onClick={() => onSceneSelect(segment.index)}
                        >
                            {/* Segment bar */}
                            <div
                                className={`
                                    w-full rounded-sm cursor-pointer transition-all duration-150
                                    ${isActive
                                        ? 'h-6 bg-teal-500 mt-1'
                                        : 'h-3 bg-slate-300 hover:bg-slate-400 mt-2.5'
                                    }
                                    ${isHovered && !isActive ? 'bg-slate-400' : ''}
                                `}
                            >
                                {/* Scene number indicator inside active segment */}
                                {isActive && (
                                    <div className="absolute inset-0 flex items-center justify-center mt-1">
                                        <span className="text-[10px] font-medium text-white/80">
                                            {segment.index + 1}
                                        </span>
                                    </div>
                                )}
                            </div>

                            {/* Tooltip */}
                            {isHovered && (
                                <div className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-20 pointer-events-none">
                                    <div className="bg-slate-900 text-white text-xs py-1.5 px-2.5 rounded shadow-lg whitespace-nowrap">
                                        <div className="font-medium">Scene {segment.index + 1}: {segment.scene.title}</div>
                                        <div className="text-slate-400 text-[10px] mt-0.5">
                                            {formatTime(segment.duration)} • ID: {segment.scene.scene_id}
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Trim handles for active segment */}
                            {isActive && activeScene?.matched_scene && (
                                <>
                                    {/* Start handle */}
                                    <div
                                        className="absolute left-0 top-0 w-2 h-8 cursor-ew-resize z-10 group/handle mt-0"
                                        onMouseDown={handleMouseDown('start')}
                                    >
                                        <div className="absolute left-0 top-1 w-1.5 h-6 bg-teal-700 rounded-l hover:bg-teal-800 flex items-center justify-center">
                                            <div className="w-0.5 h-3 bg-teal-300/50 rounded"></div>
                                        </div>
                                        {/* Handle tooltip */}
                                        <div className="absolute bottom-full mb-1 left-0 opacity-0 group-hover/handle:opacity-100 transition-opacity z-30">
                                            <div className="bg-slate-800 text-white text-[10px] py-0.5 px-1.5 rounded whitespace-nowrap">
                                                {formatTime(activeScene.matched_scene.start_time)}
                                            </div>
                                        </div>
                                    </div>

                                    {/* End handle */}
                                    <div
                                        className="absolute right-0 top-0 w-2 h-8 cursor-ew-resize z-10 group/handle mt-0"
                                        onMouseDown={handleMouseDown('end')}
                                    >
                                        <div className="absolute right-0 top-1 w-1.5 h-6 bg-teal-700 rounded-r hover:bg-teal-800 flex items-center justify-center">
                                            <div className="w-0.5 h-3 bg-teal-300/50 rounded"></div>
                                        </div>
                                        {/* Handle tooltip */}
                                        <div className="absolute bottom-full mb-1 right-0 opacity-0 group-hover/handle:opacity-100 transition-opacity z-30">
                                            <div className="bg-slate-800 text-white text-[10px] py-0.5 px-1.5 rounded whitespace-nowrap">
                                                {formatTime(activeScene.matched_scene.end_time)}
                                            </div>
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>
                    );
                })}

                {/* Playhead indicator line (optional - for future) */}
            </div>


        </div>
    );
}
