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

    if (input.isProcessing || input.videoGenerating) {
        return 'loading';
    }

    if (input.allScenesReady) {
        return 'ready';
    }

    return 'incomplete';
}
