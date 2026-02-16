import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '@/lib/types';
import { getVisibleEvents } from './eventStreamUtils';

function event(type: AgentEvent['type'], extra: Partial<AgentEvent> = {}): AgentEvent {
    return {
        ts: '2026-02-15T00:00:00.000Z',
        type,
        ...extra,
    };
}

describe('getVisibleEvents', () => {
    it('deduplicates consecutive events with the same displayed label', () => {
        const visible = getVisibleEvents([
            event('run_start'),
            event('tool_start', { name: 'match_scene_to_video' }),
            event('tool_start', { name: 'match_scene_to_video' }),
            event('tool_end', { name: 'match_scene_to_video', status: 'ok' }),
        ], 20);

        expect(visible.filter(e => e.type === 'tool_start' && e.name === 'match_scene_to_video')).toHaveLength(1);
        expect(visible).toHaveLength(3);
    });

    it('keeps events when the displayed label is different', () => {
        const visible = getVisibleEvents([
            event('tool_start', { name: 'match_scene_to_video', input: { requests: [{}] } }),
            event('tool_start', { name: 'match_scene_to_video', input: { requests: [{}, {}] } }),
        ], 20);

        expect(visible).toHaveLength(2);
    });

    it('deduplicates across hidden internal events', () => {
        const visible = getVisibleEvents([
            event('tool_start', { name: 'update_storyboard' }),
            event('storyboard_update'),
            event('tool_start', { name: 'update_storyboard' }),
        ], 20);

        expect(visible).toHaveLength(1);
        expect(visible[0].name).toBe('update_storyboard');
    });

    it('returns only the latest maxVisible deduped entries', () => {
        const visible = getVisibleEvents([
            event('run_start'),
            event('tool_start', { name: 'update_storyboard' }),
            event('tool_end', { name: 'update_storyboard', status: 'ok' }),
        ], 2);

        expect(visible).toHaveLength(2);
        expect(visible[0].type).toBe('tool_start');
        expect(visible[1].type).toBe('tool_end');
    });
});
