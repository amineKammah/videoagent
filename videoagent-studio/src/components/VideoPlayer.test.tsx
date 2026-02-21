import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { StoryboardScene, VideoMetadata } from '@/lib/types';

type SessionStoreState = {
  session: { id: string } | null;
  scenes: StoryboardScene[];
  setScenes: (scenes: StoryboardScene[]) => void;
  sendMessage: (message: string) => Promise<void>;
  user: { id: string } | null;
};

const apiMock = {
  getVideoMetadata: vi.fn(),
  renderVideo: vi.fn(),
  updateStoryboard: vi.fn(),
};

let storeState: SessionStoreState;
let fetchMock: ReturnType<typeof vi.fn>;

vi.mock('@/lib/api', () => ({
  api: apiMock,
}));

vi.mock('@/store/session', () => ({
  useSessionStore: <T,>(selector: (state: SessionStoreState) => T): T => selector(storeState),
}));

vi.mock('./SceneTimeline', () => ({
  SceneTimeline: () => null,
}));

import {
  VideoPlayer,
  type VideoPlayerRef,
  resolveMediaSource,
  resolveMetadataVideoSource,
  resolveSceneAudioSource,
} from './VideoPlayer';

const baseScene: StoryboardScene = {
  scene_id: 'scene-1',
  title: 'Scene 1',
  purpose: 'Purpose',
  script: 'Script',
  use_voice_over: false,
  matched_scene: {
    segment_type: 'video_clip',
    source_video_id: 'video-1',
    start_time: 1,
    end_time: 5,
    description: 'Clip',
    keep_original_audio: false,
  },
};

const signedMetadata: VideoMetadata = {
  id: 'video-1',
  path: 'gs://bink_video_storage_alpha/companies/company-1/videos/clip.mp4',
  url: 'https://signed.example/video-1.mp4',
  filename: 'clip.mp4',
  duration: 10,
  resolution: [1920, 1080],
  fps: 24,
};

describe('VideoPlayer media behavior', () => {
  beforeEach(() => {
    storeState = {
      session: { id: 'session-1' },
      scenes: [baseScene],
      setScenes: vi.fn(),
      sendMessage: vi.fn().mockResolvedValue(undefined),
      user: { id: 'user-1' },
    };

    apiMock.getVideoMetadata.mockReset();
    apiMock.getVideoMetadata.mockResolvedValue(signedMetadata);
    apiMock.renderVideo.mockReset();
    apiMock.updateStoryboard.mockReset();

    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(async () => undefined);
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined);
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(function (this: HTMLMediaElement) {
      this.dispatchEvent(new Event('loadeddata'));
      this.dispatchEvent(new Event('canplay'));
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('resolves only safe browser-playable media URLs', () => {
    expect(resolveMediaSource('https://cdn.example/video.mp4')).toBe('https://cdn.example/video.mp4');
    expect(resolveMediaSource('blob:https://app.example/id-123')).toBe('blob:https://app.example/id-123');
    expect(resolveMediaSource('gs://bink_video_storage_alpha/companies/c1/videos/a.mp4')).toBeNull();
    expect(resolveMediaSource('/local/path.mp4')).toBeNull();

    expect(resolveMetadataVideoSource(signedMetadata)).toBe('https://signed.example/video-1.mp4');
    expect(
      resolveMetadataVideoSource({
        ...signedMetadata,
        url: undefined,
      }),
    ).toBeNull();

    expect(
      resolveSceneAudioSource({
        ...baseScene,
        voice_over: {
          script: 'Voice over',
          audio_url: 'https://signed.example/vo.wav',
        },
      }),
    ).toBe('https://signed.example/vo.wav');
  });

  it('uses signed metadata URL for playback, not gs:// path', async () => {
    const playerRef = createRef<VideoPlayerRef>();
    const { container } = render(<VideoPlayer ref={playerRef} />);

    await waitFor(() => {
      expect(apiMock.getVideoMetadata).toHaveBeenCalledWith('video-1');
    });

    await act(async () => {
      playerRef.current?.play();
    });

    const video = container.querySelector('video');
    expect(video).not.toBeNull();
    expect(video?.getAttribute('src')).toBe('https://signed.example/video-1.mp4');
  });

  it('retries metadata refresh once on video error, then surfaces error', async () => {
    const playerRef = createRef<VideoPlayerRef>();
    const { container } = render(<VideoPlayer ref={playerRef} />);

    await waitFor(() => {
      expect(apiMock.getVideoMetadata).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      playerRef.current?.play();
    });

    const video = container.querySelector('video');
    expect(video).not.toBeNull();

    fireEvent.error(video as HTMLVideoElement);

    await waitFor(() => {
      expect(apiMock.getVideoMetadata).toHaveBeenCalledTimes(2);
    });

    fireEvent.error(video as HTMLVideoElement);

    await waitFor(() => {
      expect(screen.getByText('Failed to load video file. It may be missing or inaccessible.')).toBeInTheDocument();
    });
  });

  it('uses voice-over signed audio URL and mutes source video while VO plays', async () => {
    storeState = {
      ...storeState,
      scenes: [
        {
          ...baseScene,
          use_voice_over: true,
          voice_over: {
            script: 'VO',
            audio_url: 'https://signed.example/voice-over.wav',
            duration: 3,
          },
        },
      ],
    };

    const playerRef = createRef<VideoPlayerRef>();
    const { container } = render(<VideoPlayer ref={playerRef} />);

    await waitFor(() => {
      expect(apiMock.getVideoMetadata).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      playerRef.current?.play();
    });

    const video = container.querySelector('video') as HTMLVideoElement | null;
    const audio = container.querySelector('audio') as HTMLAudioElement | null;
    expect(video).not.toBeNull();
    expect(audio).not.toBeNull();
    expect(video?.muted).toBe(true);
    expect(audio?.getAttribute('src')).toBe('https://signed.example/voice-over.wav');
  });

  it('keeps loading state until both video and voice-over are ready', async () => {
    storeState = {
      ...storeState,
      scenes: [
        {
          ...baseScene,
          use_voice_over: true,
          voice_over: {
            script: 'VO',
            audio_url: 'https://signed.example/voice-over.wav',
            duration: 3,
          },
        },
      ],
    };

    vi.mocked(HTMLMediaElement.prototype.load).mockImplementation(function (this: HTMLMediaElement) {
      if (this instanceof HTMLVideoElement) {
        this.dispatchEvent(new Event('loadeddata'));
        this.dispatchEvent(new Event('canplay'));
      }
    });

    const playerRef = createRef<VideoPlayerRef>();
    const { container } = render(<VideoPlayer ref={playerRef} />);

    await waitFor(() => {
      expect(apiMock.getVideoMetadata).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      playerRef.current?.play();
    });

    expect(screen.getByText('Loading assets...')).toBeInTheDocument();

    const playMock = vi.mocked(HTMLMediaElement.prototype.play);
    expect(playMock).not.toHaveBeenCalled();

    const audio = container.querySelector('audio') as HTMLAudioElement | null;
    expect(audio).not.toBeNull();

    act(() => {
      audio?.dispatchEvent(new Event('loadeddata'));
      audio?.dispatchEvent(new Event('canplay'));
    });

    await waitFor(() => {
      expect(playMock).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(screen.queryByText('Loading assets...')).not.toBeInTheDocument();
    });
  });

  it('falls back to direct signed URL open when export fetch fails', async () => {
    storeState = {
      ...storeState,
      user: null,
    };

    const outputUrl = 'https://signed.example/exported-video.mp4';
    apiMock.renderVideo.mockResolvedValue({
      render_result: {
        success: true,
        output_path: outputUrl,
      },
    });
    fetchMock.mockRejectedValue(new Error('CORS'));

    const realCreateElement = document.createElement.bind(document);
    const anchors: HTMLAnchorElement[] = [];
    vi.spyOn(document, 'createElement').mockImplementation(
      ((tagName: string) => {
        const el = realCreateElement(tagName);
        if (tagName.toLowerCase() === 'a') {
          anchors.push(el as HTMLAnchorElement);
        }
        return el;
      }) as typeof document.createElement,
    );

    render(<VideoPlayer />);

    fireEvent.click(screen.getByTitle('Export Video'));

    await waitFor(() => {
      expect(apiMock.renderVideo).toHaveBeenCalledWith('session-1');
    });

    await waitFor(() => {
      expect(anchors.length).toBeGreaterThan(0);
    });

    const fallbackAnchor = anchors.find((anchor) => anchor.target === '_blank');
    expect(fallbackAnchor).toBeDefined();
    expect(fallbackAnchor?.href).toContain(outputUrl);
  });
});
