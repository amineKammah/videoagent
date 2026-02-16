import { AgentEvent } from '@/lib/types';
import { getEventDisplay } from './eventDisplay';

const HIDDEN_EVENT_TYPES: AgentEvent['type'][] = ['video_render_start', 'storyboard_update'];

function getDisplayKey(event: AgentEvent): string {
    const display = getEventDisplay(event);
    return `${display.icon}|${display.label}`;
}

export function getVisibleEvents(events: AgentEvent[], maxVisible = 8): AgentEvent[] {
    const filteredEvents = events.filter(event => !HIDDEN_EVENT_TYPES.includes(event.type));
    const dedupedEvents: AgentEvent[] = [];
    let previousDisplayKey: string | null = null;

    for (const event of filteredEvents) {
        const displayKey = getDisplayKey(event);
        if (displayKey === previousDisplayKey) {
            continue;
        }
        dedupedEvents.push(event);
        previousDisplayKey = displayKey;
    }

    return dedupedEvents.slice(-maxVisible);
}
