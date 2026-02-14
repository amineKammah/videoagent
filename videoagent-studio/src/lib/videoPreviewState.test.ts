import { describe, expect, it } from 'vitest';

import { getVideoPreviewState } from './videoPreviewState';

describe('getVideoPreviewState', () => {
    it('hides preview when nothing has been generated yet', () => {
        const state = getVideoPreviewState({
            hasScenes: false,
            allScenesReady: false,
            isProcessing: false,
            videoGenerating: false,
        });

        expect(state).toBe('hidden');
    });

    it('keeps loading while a run is still processing even with partial scenes', () => {
        const state = getVideoPreviewState({
            hasScenes: true,
            allScenesReady: false,
            isProcessing: true,
            videoGenerating: false,
        });

        expect(state).toBe('loading');
    });

    it('keeps preview ready when all scenes are matched during background processing', () => {
        const state = getVideoPreviewState({
            hasScenes: true,
            allScenesReady: true,
            isProcessing: true,
            videoGenerating: true,
        });

        expect(state).toBe('ready');
    });

    it('only becomes ready when every scene is matched', () => {
        const state = getVideoPreviewState({
            hasScenes: true,
            allScenesReady: true,
            isProcessing: false,
            videoGenerating: false,
        });

        expect(state).toBe('ready');
    });

    it('shows incomplete when run ended but some scenes are unresolved', () => {
        const state = getVideoPreviewState({
            hasScenes: true,
            allScenesReady: false,
            isProcessing: false,
            videoGenerating: false,
        });

        expect(state).toBe('incomplete');
    });
});
