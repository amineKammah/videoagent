'use client';

import { AgentEvent } from '@/lib/types';

interface EventItemProps {
    event: AgentEvent;
    isLatest?: boolean;
}

export function EventItem({ event, isLatest = false }: EventItemProps) {
    const { icon, label, color, isAnimated } = getEventDisplay(event);

    return (
        <div
            className={`flex items-center gap-2 text-sm transition-opacity duration-300 ${isLatest ? 'opacity-100' : 'opacity-60'
                }`}
        >
            <span className={`${isAnimated && isLatest ? 'animate-pulse' : ''}`}>
                {icon}
            </span>
            <span className={color}>{label}</span>
            {isLatest && event.type !== 'run_end' && (
                <span className="inline-flex gap-1 ml-1">
                    <span className="w-1 h-1 rounded-full bg-teal-500 animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-1 h-1 rounded-full bg-teal-500 animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-1 h-1 rounded-full bg-teal-500 animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
            )}
        </div>
    );
}

interface EventDisplay {
    icon: string;
    label: string;
    color: string;
    isAnimated: boolean;
}

function getEventDisplay(event: AgentEvent): EventDisplay {
    switch (event.type) {
        case 'run_start':
            return {
                icon: '🧠',
                label: 'Thinking...',
                color: 'text-blue-600',
                isAnimated: true,
            };

        case 'run_end':
            return {
                icon: '✨',
                label: 'Complete',
                color: 'text-green-600',
                isAnimated: false,
            };

        case 'tool_start':
            if (event.name === 'match_scene_to_video') {
                const count = event.input?.requests?.length;
                const scenesText = count ? ` for ${count} scenes` : '';
                return {
                    icon: '🎞️',
                    label: `Evaluating videos${scenesText} to find the right scenes...`,
                    color: 'text-blue-600',
                    isAnimated: true,
                };
            }
            if (event.name === 'generate_voice_overs') {
                return {
                    icon: '🎙️',
                    label: 'Generating voice-overs...',
                    color: 'text-blue-600',
                    isAnimated: true,
                };
            }
            if (event.name === 'update_storyboard') {
                return {
                    icon: '📝',
                    label: 'Updating storyboard...',
                    color: 'text-blue-600',
                    isAnimated: true,
                };
            }
            return {
                icon: '🔧',
                label: `Calling ${formatToolName(event.name)}...`,
                color: 'text-blue-600',
                isAnimated: true,
            };

        case 'tool_end':
            if (event.status === 'ok') {
                return {
                    icon: '✓',
                    label: `${formatToolName(event.name)} complete`,
                    color: 'text-green-600',
                    isAnimated: false,
                };
            } else {
                return {
                    icon: '✗',
                    label: `${formatToolName(event.name)} failed`,
                    color: 'text-red-600',
                    isAnimated: false,
                };
            }



        case 'video_render_complete':
            return {
                icon: '✅',
                label: 'Video preparation complete',
                color: 'text-green-600',
                isAnimated: false,
            };

        case 'auto_render_start':
            return {
                icon: '🎬',
                label: 'Rendering video...',
                color: 'text-blue-600',
                isAnimated: true,
            };

        case 'auto_render_end':
            if (event.status === 'ok') {
                return {
                    icon: '🎥',
                    label: 'Video ready!',
                    color: 'text-green-600',
                    isAnimated: false,
                };
            } else {
                return {
                    icon: '❌',
                    label: 'Render failed',
                    color: 'text-red-600',
                    isAnimated: false,
                };
            }

        case 'auto_render_skipped':
            return {
                icon: '⏭️',
                label: event.error || 'Render skipped',
                color: 'text-yellow-600',
                isAnimated: false,
            };

        case 'segment_warning':
            return {
                icon: '⚠️',
                label: event.message || 'Segment warning',
                color: 'text-yellow-600',
                isAnimated: false,
            };

        default:
            return {
                icon: '•',
                label: event.message || event.type,
                color: 'text-slate-500',
                isAnimated: false,
            };
    }
}

function formatToolName(name?: string): string {
    if (!name) return 'tool';
    // Convert snake_case to Title Case
    return name
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}
