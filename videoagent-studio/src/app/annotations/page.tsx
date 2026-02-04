'use client';

import { useState, useEffect, useRef, useMemo } from 'react';
import { useSessionStore } from '@/store/session';
import { useAnnotationStore } from '@/store/annotations';
import { api } from '@/lib/api';
import { Annotation, Severity, SessionListItem, AnnotationMetrics as MetricsType, SessionStatus, ComparisonResult } from '@/lib/types';
import { AnnotationDialog } from '@/components/AnnotationDialog';
import { AnnotationPanel } from '@/components/AnnotationPanel';
import { AnnotationMetrics } from '@/components/AnnotationMetrics';
import { AnnotationComparison } from '@/components/AnnotationComparison';
import { VideoPlayer, VideoPlayerRef } from '@/components/VideoPlayer';

// Format time as M:SS
const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
};

export default function AnnotationsPage() {
    // Session Store
    const session = useSessionStore(state => state.session);
    const scenes = useSessionStore(state => state.scenes);
    const loadSession = useSessionStore(state => state.loadSession);

    // Annotation Store
    const annotations = useAnnotationStore(state => state.annotations);
    const currentAnnotatorId = useAnnotationStore(state => state.currentAnnotatorId);
    const currentAnnotatorName = useAnnotationStore(state => state.currentAnnotatorName);
    const loadAnnotations = useAnnotationStore(state => state.loadAnnotations);
    const addAnnotation = useAnnotationStore(state => state.addAnnotation);
    const updateAnnotation = useAnnotationStore(state => state.updateAnnotation);
    const setAnnotator = useAnnotationStore(state => state.setAnnotator);

    // Page State
    const [sessions, setSessions] = useState<SessionListItem[]>([]);
    const [isLoadingSessions, setIsLoadingSessions] = useState(true);
    const [showOnlyAnnotated, setShowOnlyAnnotated] = useState(false);

    // Stats
    const [annotationCounts, setAnnotationCounts] = useState<Record<string, number>>({});
    const [sessionStatuses, setSessionStatuses] = useState<Record<string, SessionStatus>>({});
    const [sessionConflicts, setSessionConflicts] = useState<Record<string, number>>({});

    // Metrics State
    const [showMetrics, setShowMetrics] = useState(false);
    const [metrics, setMetrics] = useState<MetricsType | null>(null);

    // Comparison State
    const [viewMode, setViewMode] = useState<'annotate' | 'compare'>('annotate');
    const [comparison, setComparison] = useState<ComparisonResult | null>(null);
    const [isLoadingComparison, setIsLoadingComparison] = useState(false);

    // Player state
    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const playerRef = useRef<VideoPlayerRef>(null);

    // Dialog state
    const [showAnnotationDialog, setShowAnnotationDialog] = useState(false);
    const [editingAnnotation, setEditingAnnotation] = useState<Annotation | null>(null);

    // Load sessions and stats on mount
    useEffect(() => {
        const fetchSessionsAndStats = async () => {
            setIsLoadingSessions(true);
            try {
                const [sessionsData, counts, statuses, conflicts] = await Promise.all([
                    api.listSessions(),
                    api.getSessionAnnotationCounts(),
                    api.getAllSessionStatuses(),
                    api.getAllSessionConflicts()
                ]);

                // Sort by recent
                const sorted = (sessionsData?.sessions || []).sort((a, b) =>
                    new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                );

                setSessions(sorted);
                setAnnotationCounts(counts);
                setSessionStatuses(statuses);
                setSessionConflicts(conflicts);
            } catch (e) {
                console.error("Failed to load sessions", e);
            } finally {
                setIsLoadingSessions(false);
            }
        };
        fetchSessionsAndStats();
    }, []);

    // Derived
    const hasMatchedScenes = scenes.some(s => s.matched_scene);

    // Filter sessions
    const filteredSessions = useMemo(() => {
        if (!showOnlyAnnotated) return sessions;
        return sessions.filter(s =>
            (annotationCounts[s.session_id] || 0) > 0 ||
            sessionStatuses[s.session_id] === 'reviewed'
        );
    }, [sessions, showOnlyAnnotated, annotationCounts, sessionStatuses]);

    // Calculate total duration for markers
    const totalDuration = useMemo(() => {
        return scenes.reduce((acc, scene) => {
            const duration = (scene.matched_scene?.end_time || 0) - (scene.matched_scene?.start_time || 0);
            return acc + duration;
        }, 0);
    }, [scenes]);

    // Determine segments for reverse lookup in markers
    const segmentStarts = useMemo(() => {
        let current = 0;
        const starts: number[] = [];
        scenes.forEach(scene => {
            starts.push(current);
            const duration = (scene.matched_scene?.end_time || 0) - (scene.matched_scene?.start_time || 0);
            current += duration;
        });
        return starts;
    }, [scenes]);

    // Load annotations
    useEffect(() => {
        if (session?.id) {
            loadAnnotations(session.id);

            if (viewMode === 'compare') {
                handleViewModeChange('compare');
            }

            setCurrentTime(0);
            setIsPlaying(false);
        }
    }, [session?.id, loadAnnotations, currentAnnotatorId]);

    const handleSessionSelect = async (sessionId: string) => {
        await loadSession(sessionId);
    };

    const handleAddAnnotation = () => {
        // Pause video using exposed ref
        if (playerRef.current) {
            playerRef.current.pause();
        }

        setEditingAnnotation(null);
        setShowAnnotationDialog(true);
    };

    const handleEditAnnotation = (annotation: Annotation) => {
        setEditingAnnotation(annotation);
        setShowAnnotationDialog(true);
    };

    const handleSubmitAnnotation = async (data: {
        category: string;
        description: string;
        severity: Severity;
    }) => {
        if (!session?.id) return;

        // Find active scene based on current time
        let activeSceneId = '';
        let sceneIndex = 0;
        for (let i = segmentStarts.length - 1; i >= 0; i--) {
            if (currentTime >= segmentStarts[i]) {
                sceneIndex = i;
                activeSceneId = scenes[i].scene_id;
                break;
            }
        }

        if (!activeSceneId) return;

        const sceneStartTime = segmentStarts[sceneIndex];
        const relativeTime = currentTime - sceneStartTime;

        if (editingAnnotation) {
            await updateAnnotation(editingAnnotation.id, data);
        } else {
            await addAnnotation({
                session_id: session.id,
                scene_id: activeSceneId,
                timestamp: relativeTime,
                global_timestamp: currentTime,
                category: data.category,
                description: data.description,
                severity: data.severity,
            });
            // Update local count
            setAnnotationCounts(prev => ({
                ...prev,
                [session.id]: (prev[session.id] || 0) + 1
            }));

            // Auto-mark as reviewed if not already
            if ((sessionStatuses[session.id] || 'pending') !== 'reviewed') {
                try {
                    await api.setSessionStatus(session.id, 'reviewed');
                    setSessionStatuses(prev => ({
                        ...prev,
                        [session.id]: 'reviewed'
                    }));
                } catch (e) {
                    console.error("Failed to auto-mark as reviewed", e);
                }
            }

            // If in compare mode, refresh comparison
            if (viewMode === 'compare') {
                handleViewModeChange('compare');
            }
        }

        setShowAnnotationDialog(false);
        setEditingAnnotation(null);
    };

    const handleResolveAnnotations = async (ids: string[]) => {
        if (!session?.id) return;
        try {
            await api.resolveAnnotations(ids, currentAnnotatorName || 'User');
            // Refresh comparison
            const data = await api.compareAnnotations(session.id);
            setComparison(data);
            // Refresh conflicts
            const conflicts = await api.getAllSessionConflicts();
            setSessionConflicts(conflicts);
        } catch (e) {
            console.error("Failed to resolve annotations", e);
        }
    };

    const handleDeleteComparisonAnnotation = async (id: string) => {
        if (!session?.id) return;
        try {
            await api.rejectAnnotations([id], currentAnnotatorName || 'User');
            // Refresh comparison
            const data = await api.compareAnnotations(session.id);
            setComparison(data);
            // Also refresh stats and conflicts
            const [stats, conflicts] = await Promise.all([
                api.getSessionAnnotationCounts(),
                api.getAllSessionConflicts()
            ]);
            setAnnotationCounts(stats);
            setSessionConflicts(conflicts);
            // Refresh main list if loaded
            loadAnnotations(session.id);
        } catch (e) {
            console.error("Failed to delete (reject) annotation", e);
        }
    };

    const handleToggleStatus = async () => {
        if (!session?.id) return;

        const currentStatus = sessionStatuses[session.id] || 'pending';
        const newStatus: SessionStatus = currentStatus === 'pending' ? 'reviewed' : 'pending';

        try {
            await api.updateSessionStatus(session.id, newStatus, currentAnnotatorName || 'User');
            setSessionStatuses(prev => ({
                ...prev,
                [session.id]: newStatus
            }));
            // Also refresh conflicts as status change counts as participation
            const conflicts = await api.getAllSessionConflicts();
            setSessionConflicts(conflicts);
        } catch (e) {
            console.error("Failed to update status", e);
        }
    };

    const handleSeek = (time: number) => {
        if (playerRef.current) {
            playerRef.current.seekTo(time);
        }
    };

    const handleViewMetrics = async () => {
        if (!session?.id) return;
        try {
            const data = await api.getAnnotationMetrics(session.id);
            setMetrics(data);
            setShowMetrics(true);
        } catch (e) {
            console.error("Failed to load metrics", e);
        }
    };

    const handleViewModeChange = async (mode: 'annotate' | 'compare') => {
        setViewMode(mode);
        if (mode === 'compare' && session?.id) {
            setIsLoadingComparison(true);
            try {
                const data = await api.compareAnnotations(session.id);
                setComparison(data);
            } catch (e) {
                console.error("Failed to load comparison", e);
            } finally {
                setIsLoadingComparison(false);
            }
        }
    };

    return (
        <div className="min-h-screen bg-slate-100 flex flex-col">
            {/* Header */}
            <header className="bg-white border-b border-slate-200 px-6 py-4 flex-shrink-0">
                <div className="max-w-7xl mx-auto flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <a href="/" className="text-slate-500 hover:text-slate-700">
                            ← Studio
                        </a>
                        <h1 className="text-xl font-semibold text-slate-800">
                            📝 Video Annotations
                        </h1>
                        {session && (
                            <>
                                <button
                                    onClick={handleToggleStatus}
                                    className={`ml-4 px-3 py-1 text-xs font-medium rounded-full flex items-center gap-1 transition-colors border ${(sessionStatuses[session.id] || 'pending') === 'reviewed'
                                        ? 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100'
                                        : 'bg-white text-slate-500 border-slate-200 hover:text-slate-700 hover:bg-slate-50'
                                        }`}
                                >
                                    {(sessionStatuses[session.id] || 'pending') === 'reviewed' ? (
                                        <>
                                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
                                            Reviewed
                                        </>
                                    ) : (
                                        <>
                                            <span className="w-3 h-3 border border-slate-300 rounded-sm"></span>
                                            Mark as Reviewed
                                        </>
                                    )}
                                </button>
                                <button
                                    onClick={handleViewMetrics}
                                    className="ml-2 px-3 py-1 bg-slate-100 hover:bg-slate-200 text-slate-600 text-xs font-medium rounded-full flex items-center gap-1 transition-colors"
                                >
                                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
                                    Dashboard
                                </button>

                                <div className="ml-4 h-6 w-px bg-slate-300 mx-2"></div>

                                <div className="bg-slate-100 p-1 rounded-lg flex items-center">
                                    <button
                                        onClick={() => handleViewModeChange('annotate')}
                                        className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${viewMode === 'annotate' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                                            }`}
                                    >
                                        Annotate
                                    </button>
                                    <button
                                        onClick={() => handleViewModeChange('compare')}
                                        className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${viewMode === 'compare' ? 'bg-white text-teal-700 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                                            }`}
                                    >
                                        Compare
                                    </button>
                                </div>
                            </>
                        )}
                    </div>
                    {/* Removed Set Name button */}
                </div>
            </header>

            <div className="flex-1 flex overflow-hidden">
                {/* Session Sidebar */}
                <aside className="w-80 bg-white border-r border-slate-200 flex flex-col overflow-hidden">
                    <div className="p-4 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
                        <h2 className="font-semibold text-slate-700 text-sm uppercase tracking-wider">Sessions</h2>

                        {/* Filter Toggle */}
                        <label className="flex items-center gap-2 cursor-pointer select-none">
                            <input
                                type="checkbox"
                                checked={showOnlyAnnotated}
                                onChange={(e) => setShowOnlyAnnotated(e.target.checked)}
                                className="w-4 h-4 text-teal-600 rounded focus:ring-teal-500 border-gray-300"
                            />
                            <span className="text-xs text-slate-600 font-medium whitespace-nowrap">
                                Reviewed / Annotated
                            </span>
                        </label>
                    </div>
                    <div className="flex-1 overflow-y-auto">
                        {isLoadingSessions ? (
                            <div className="p-4 text-center text-slate-400">Loading sessions...</div>
                        ) : filteredSessions.length === 0 ? (
                            <div className="p-4 text-center text-slate-400">
                                {showOnlyAnnotated ? "No annotated sessions found" : "No sessions found"}
                            </div>
                        ) : (
                            <div className="divide-y divide-slate-100">
                                {filteredSessions.map(s => {
                                    const count = annotationCounts[s.session_id] || 0;
                                    const isSelected = session?.id === s.session_id;
                                    return (
                                        <button
                                            key={s.session_id}
                                            onClick={() => handleSessionSelect(s.session_id)}
                                            className={`w-full text-left p-4 hover:bg-slate-50 transition-colors ${isSelected ? 'bg-teal-50 border-l-4 border-teal-600' : 'border-l-4 border-transparent'
                                                }`}
                                        >
                                            <div className="flex items-center justify-between mb-1">
                                                <span className={`font-medium ${isSelected ? 'text-teal-900' : 'text-slate-800'}`}>
                                                    Session {s.session_id.slice(0, 6)}...
                                                </span>
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs text-slate-400">
                                                        {new Date(s.created_at).toLocaleDateString()}
                                                    </span>
                                                    {sessionConflicts[s.session_id] > 0 && (
                                                        <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-red-100 text-red-600 text-[10px] font-medium border border-red-200">
                                                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
                                                            {sessionConflicts[s.session_id]}
                                                        </span>
                                                    )}
                                                    {annotationCounts[s.session_id] > 0 && (
                                                        <span className="bg-slate-100 text-slate-600 text-[10px] px-1.5 py-0.5 rounded-full font-medium">
                                                            {annotationCounts[s.session_id]}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                            <div className="text-xs text-slate-500">
                                                {new Date(s.created_at).toLocaleString()}
                                            </div>
                                        </button>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </aside>

                {/* Main Content */}
                <main className="flex-1 overflow-y-auto p-6 bg-slate-100">
                    {!session ? (
                        <div className="h-full flex flex-col items-center justify-center text-slate-400">
                            <svg className="w-16 h-16 mb-4 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                            </svg>
                            <p className="text-lg font-medium">Select a session to start annotating</p>
                        </div>
                    ) : !hasMatchedScenes ? (
                        <div className="h-full flex flex-col items-center justify-center text-slate-400">
                            <p className="text-lg font-medium">This session has no generated video content.</p>
                            <p className="text-sm mt-2">Only sessions with matched scenes can be annotated.</p>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 max-w-7xl mx-auto">
                            {/* Video Player + Timeline */}
                            <div className="lg:col-span-2 space-y-4">
                                <div className="bg-black rounded-lg overflow-hidden shadow-lg relative">
                                    <VideoPlayer
                                        ref={playerRef}
                                        onTimeUpdate={setCurrentTime}
                                        onPlayChange={setIsPlaying}
                                        primaryAction={
                                            <button
                                                onClick={handleAddAnnotation}
                                                className="group bg-teal-600 hover:bg-teal-700 text-white text-sm font-medium px-4 py-2 rounded-full shadow-lg flex items-center gap-2 transition-all hover:scale-105 hover:shadow-teal-500/20 border border-transparent hover:border-teal-400"
                                            >
                                                <svg className="w-4 h-4 text-teal-100 group-hover:text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path>
                                                </svg>
                                                Add Annotation
                                            </button>
                                        }
                                        overlay={
                                            <div className="absolute bottom-16 left-0 right-0 h-4 z-20 pointer-events-none">
                                                {/* Annotation Markers Overlay */}
                                                <div className="relative w-full h-full px-4">
                                                    {viewMode === 'annotate' ? (
                                                        // Annotate Mode: Show individual markers
                                                        annotations.map(ann => {
                                                            const position = totalDuration > 0 ? (ann.global_timestamp / totalDuration) * 100 : 0;
                                                            return (
                                                                <div
                                                                    key={ann.id}
                                                                    className={`absolute w-3 h-3 rounded-full cursor-pointer transform -translate-x-1/2 -translate-y-1/2 z-30 transition-transform hover:scale-150 pointer-events-auto ${ann.severity === 'high' ? 'bg-red-500' :
                                                                        ann.severity === 'medium' ? 'bg-yellow-400' : 'bg-green-500'
                                                                        }`}
                                                                    style={{ left: `${position}%`, top: '50%' }}
                                                                    onClick={(e) => {
                                                                        e.stopPropagation();
                                                                        handleSeek(ann.global_timestamp);
                                                                    }}
                                                                    title={`${ann.annotator_name}: ${ann.category}`}
                                                                />
                                                            );
                                                        })
                                                    ) : (
                                                        // Compare Mode: Show cluster markers
                                                        comparison?.clusters.map(cluster => {
                                                            const position = totalDuration > 0 ? (cluster.center_timestamp / totalDuration) * 100 : 0;
                                                            return (
                                                                <div
                                                                    key={cluster.id}
                                                                    className={`absolute w-4 h-4 rounded-full cursor-pointer transform -translate-x-1/2 -translate-y-1/2 z-30 transition-transform hover:scale-125 pointer-events-auto border-2 border-white shadow-sm ${cluster.status === 'conflict' ? 'bg-red-500' :
                                                                        cluster.status === 'agreement' ? 'bg-teal-500' :
                                                                            'bg-blue-400'
                                                                        }`}
                                                                    style={{ left: `${position}%`, top: '50%' }}
                                                                    onClick={(e) => {
                                                                        e.stopPropagation();
                                                                        handleSeek(cluster.center_timestamp);
                                                                    }}
                                                                    title={`${cluster.status}: ${cluster.scene_id}`}
                                                                />
                                                            );
                                                        })
                                                    )}
                                                </div>
                                            </div>
                                        }
                                    />


                                </div>
                            </div>

                            {/* Annotations Panel / Comparison Panel */}
                            <div className="lg:col-span-1 h-[600px] flex flex-col">
                                <div className="bg-white rounded-lg border border-slate-200 overflow-hidden shadow-sm h-full flex flex-col">
                                    {viewMode === 'annotate' ? (
                                        <>
                                            <div className="px-4 py-3 border-b border-slate-200 bg-slate-50 flex-shrink-0">
                                                <h2 className="font-semibold text-slate-800">Annotations</h2>
                                            </div>
                                            <div className="flex-1 overflow-hidden">
                                                <AnnotationPanel
                                                    annotations={annotations}
                                                    onSeek={handleSeek}
                                                    onEdit={handleEditAnnotation}
                                                    currentAnnotatorId={currentAnnotatorId}
                                                />
                                            </div>
                                            {annotations.length === 0 && (
                                                <div className="p-6 text-center text-slate-400">
                                                    <p>No annotations yet</p>
                                                    <p className="text-sm mt-1">Click "Add Annotation" to start</p>
                                                </div>
                                            )}
                                        </>
                                    ) : (
                                        <AnnotationComparison
                                            comparison={comparison}
                                            isLoading={isLoadingComparison}
                                            onSeek={handleSeek}
                                            onEdit={handleEditAnnotation}
                                            onDelete={handleDeleteComparisonAnnotation}
                                            onResolve={handleResolveAnnotations}
                                        />
                                    )}
                                </div>
                            </div>
                        </div>
                    )}
                </main>
            </div>

            {/* Annotation Dialog */}
            <AnnotationDialog
                isOpen={showAnnotationDialog}
                onClose={() => {
                    setShowAnnotationDialog(false);
                    setEditingAnnotation(null);
                }}
                onSubmit={handleSubmitAnnotation}
                sceneNumber={1} // Simplified for now
                sceneTitle={""}
                timestamp={0}
                globalTimestamp={currentTime}
                initialData={editingAnnotation ? {
                    category: editingAnnotation.category,
                    description: editingAnnotation.description,
                    severity: editingAnnotation.severity,
                } : undefined}
                isEditing={!!editingAnnotation}
            />

            {/* Annotation Metrics Modal */}
            {
                showMetrics && metrics && (
                    <AnnotationMetrics
                        metrics={metrics}
                        sessionName={session?.id}
                        onClose={() => setShowMetrics(false)}
                    />
                )
            }
        </div >
    );
}
