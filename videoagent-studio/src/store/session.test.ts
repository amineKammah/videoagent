import { describe, expect, it } from 'vitest';

import { deriveSessionStateFromEvents, selectLatestRunEvents } from './session';
import type { AgentEvent } from '@/lib/types';

function event(type: AgentEvent['type'], extra: Partial<AgentEvent> = {}): AgentEvent {
    return {
        ts: new Date().toISOString(),
        type,
        ...extra,
    };
}

describe('deriveSessionStateFromEvents', () => {
    it('treats a run with no run_end as in progress', () => {
        const state = deriveSessionStateFromEvents([
            event('run_start'),
            event('tool_start', { name: 'update_storyboard' }),
        ]);

        expect(state.isProcessing).toBe(true);
        expect(state.videoGenerating).toBe(false);
        expect(state.videoPath).toBeNull();
    });

    it('marks processing and rendering complete when run_end arrives', () => {
        const state = deriveSessionStateFromEvents([
            event('run_start'),
            event('auto_render_start'),
            event('run_end'),
        ]);

        expect(state.isProcessing).toBe(false);
        expect(state.videoGenerating).toBe(false);
    });

    it('captures latest rendered output path', () => {
        const state = deriveSessionStateFromEvents([
            event('run_start'),
            event('auto_render_start'),
            event('auto_render_end', { output: '/tmp/old.mp4' }),
            event('run_end'),
            event('run_start'),
            event('auto_render_start'),
            event('video_render_complete', { output: '/tmp/new.mp4' }),
        ]);

        expect(state.isProcessing).toBe(true);
        expect(state.videoGenerating).toBe(false);
        expect(state.videoPath).toBe('/tmp/new.mp4');
    });
});

describe('selectLatestRunEvents', () => {
    it('returns only events from the latest run', () => {
        const events = [
            event('run_start'),
            event('tool_start', { name: 'old_tool' }),
            event('run_end'),
            event('run_start'),
            event('tool_start', { name: 'new_tool' }),
        ];

        const selected = selectLatestRunEvents(events);

        expect(selected).toHaveLength(2);
        expect(selected[0].type).toBe('run_start');
        expect(selected[1]).toMatchObject({ type: 'tool_start', name: 'new_tool' });
    });
});
