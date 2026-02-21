'use client';

import { useRef, useEffect, useCallback } from 'react';

interface SceneAnimationProps {
    /** Self-contained HTML/CSS/JS animation code to render in a sandboxed iframe. */
    htmlContent: string;
    /** Whether the video is currently playing. */
    isPlaying: boolean;
    /** Current playback time relative to the scene start (seconds). */
    currentTime: number;
}

/**
 * Wraps the animation HTML so it listens for postMessage commands
 * to sync with the video player's play/pause/seek state.
 *
 * The injected listener expects messages of the form:
 *   { type: 'animation-control', action: 'play' | 'pause' | 'seek', time?: number }
 *
 * It will call the global `__animationTimeline` GSAP timeline if it exists.
 * Animation authors should assign their master timeline to `window.__animationTimeline`.
 */
function wrapWithController(html: string): string {
    // Inject a small script that bridges postMessage → GSAP timeline control.
    const controlScript = `
<script>
(function() {
    window.addEventListener('message', function(e) {
        var data = e.data;
        if (!data || data.type !== 'animation-control') return;
        var tl = window.__animationTimeline;
        if (!tl) return;
        switch (data.action) {
            case 'play':
                tl.play();
                break;
            case 'pause':
                tl.pause();
                break;
            case 'seek':
                if (typeof data.time === 'number') {
                    tl.seek(data.time);
                }
                break;
            case 'restart':
                tl.restart();
                break;
        }
    });
})();
</script>`;
    // Insert just before </body> if present, otherwise append.
    if (html.includes('</body>')) {
        return html.replace('</body>', controlScript + '\n</body>');
    }
    return html + '\n' + controlScript;
}

/**
 * Renders a scene animation overlay in a sandboxed iframe.
 *
 * The iframe is transparent and non-interactive (pointer-events: none)
 * so it doesn't block clicks on the video player underneath.
 */
export function SceneAnimation({ htmlContent, isPlaying, currentTime }: SceneAnimationProps) {
    const iframeRef = useRef<HTMLIFrameElement>(null);
    const prevPlayingRef = useRef(isPlaying);
    const prevTimeRef = useRef(currentTime);
    const hasInitializedRef = useRef(false);

    const sendMessage = useCallback((msg: { type: string; action: string; time?: number }) => {
        const iframe = iframeRef.current;
        if (!iframe?.contentWindow) return;
        iframe.contentWindow.postMessage(msg, '*');
    }, []);

    // Wrap the HTML once so we don't re-wrap on every render.
    const wrappedHtml = useRef('');
    const prevContentRef = useRef('');
    if (htmlContent !== prevContentRef.current) {
        wrappedHtml.current = wrapWithController(htmlContent);
        prevContentRef.current = htmlContent;
        hasInitializedRef.current = false;
    }

    // When iframe loads, sync initial state.
    const handleLoad = useCallback(() => {
        hasInitializedRef.current = true;
        // Set initial play/pause state
        if (isPlaying) {
            sendMessage({ type: 'animation-control', action: 'play' });
        } else {
            sendMessage({ type: 'animation-control', action: 'pause' });
        }
    }, [isPlaying, sendMessage]);

    // Sync play/pause changes.
    useEffect(() => {
        if (!hasInitializedRef.current) return;
        if (isPlaying !== prevPlayingRef.current) {
            sendMessage({
                type: 'animation-control',
                action: isPlaying ? 'play' : 'pause',
            });
            prevPlayingRef.current = isPlaying;
        }
    }, [isPlaying, sendMessage]);

    // Sync seek — only when there's a significant jump (> 0.5s delta from expected position).
    useEffect(() => {
        if (!hasInitializedRef.current) return;
        const delta = Math.abs(currentTime - prevTimeRef.current);
        // Normal playback ticks are small; only send seek on jumps.
        if (delta > 0.5) {
            sendMessage({ type: 'animation-control', action: 'seek', time: currentTime });
        }
        prevTimeRef.current = currentTime;
    }, [currentTime, sendMessage]);

    return (
        <iframe
            ref={iframeRef}
            srcDoc={wrappedHtml.current}
            onLoad={handleLoad}
            title="Scene animation overlay"
            sandbox="allow-scripts allow-same-origin"
            className="absolute inset-0 w-full h-full border-none pointer-events-none z-10"
            style={{ background: 'transparent' }}
        />
    );
}
