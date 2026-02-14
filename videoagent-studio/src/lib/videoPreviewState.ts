export type VideoPreviewState = 'hidden' | 'loading' | 'ready' | 'incomplete';

interface VideoPreviewStateInput {
    hasScenes: boolean;
    allScenesReady: boolean;
    isProcessing: boolean;
    videoGenerating: boolean;
}

export function getVideoPreviewState(input: VideoPreviewStateInput): VideoPreviewState {
    if (!input.hasScenes && !input.videoGenerating) {
        return 'hidden';
    }

    if (input.allScenesReady) {
        return 'ready';
    }

    if (input.isProcessing || input.videoGenerating) {
        return 'loading';
    }

    return 'incomplete';
}
