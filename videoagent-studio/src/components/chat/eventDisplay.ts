import { AgentEvent } from '@/lib/types';

export interface EventDisplay {
    icon: string;
    label: string;
    color: string;
    isAnimated: boolean;
}

export function getEventDisplay(event: AgentEvent): EventDisplay {
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
                const count = event.input && typeof event.input === 'object' && 'requests' in event.input
                    ? (event.input as { requests?: unknown[] }).requests?.length
                    : undefined;
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
            if (event.name === 'generate_voiceover_v3') {
                return {
                    icon: '🎙️',
                    label: 'Generating v3 voice-overs...',
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
                label: `Calling ${formatEventName(event.name)}...`,
                color: 'text-blue-600',
                isAnimated: true,
            };

        case 'tool_end':
            if (event.status === 'ok') {
                return {
                    icon: '✓',
                    label: `${formatEventName(event.name)} complete`,
                    color: 'text-green-600',
                    isAnimated: false,
                };
            } else {
                return {
                    icon: '✗',
                    label: `${formatEventName(event.name)} failed`,
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
                label: event.message || formatEventName(event.type),
                color: 'text-slate-500',
                isAnimated: false,
            };
    }
}

function formatEventName(name?: string): string {
    if (!name) return 'Event';
    // Convert snake_case to Title Case
    return name
        .split('_')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1))
        .join(' ');
}
