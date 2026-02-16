'use client';

import { AgentEvent } from '@/lib/types';
import { getEventDisplay } from './eventDisplay';

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
