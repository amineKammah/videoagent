'use client';

import { useState, useMemo } from 'react';
import { Annotation, Severity } from '@/lib/types';
import { useAnnotationStore } from '@/store/annotations';

interface AnnotationPanelProps {
    annotations: Annotation[];
    onSeek: (globalTimestamp: number) => void;
    onEdit: (annotation: Annotation) => void;
    currentAnnotatorId?: string;
}

const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
};

const severityColors: Record<Severity, { bg: string; text: string; dot: string }> = {
    high: { bg: 'bg-red-50', text: 'text-red-700', dot: 'bg-red-500' },
    medium: { bg: 'bg-yellow-50', text: 'text-yellow-700', dot: 'bg-yellow-500' },
    low: { bg: 'bg-green-50', text: 'text-green-700', dot: 'bg-green-500' },
};

export function AnnotationPanel({
    annotations,
    onSeek,
    onEdit,
    currentAnnotatorId,
}: AnnotationPanelProps) {
    const [isExpanded, setIsExpanded] = useState(true);
    const [showOnlyMine, setShowOnlyMine] = useState(false);
    const [filterSeverity, setFilterSeverity] = useState<Severity | 'all'>('all');

    const deleteAnnotation = useAnnotationStore(state => state.deleteAnnotation);

    const filteredAnnotations = useMemo(() => {
        let filtered = annotations;

        if (showOnlyMine && currentAnnotatorId) {
            filtered = filtered.filter(a => a.annotator_id === currentAnnotatorId);
        }

        if (filterSeverity !== 'all') {
            filtered = filtered.filter(a => a.severity === filterSeverity);
        }

        return filtered;
    }, [annotations, showOnlyMine, currentAnnotatorId, filterSeverity]);

    const handleDelete = async (id: string) => {
        if (confirm('Are you sure you want to delete this annotation?')) {
            await deleteAnnotation(id);
        }
    };

    if (annotations.length === 0) {
        return null;
    }

    return (
        <div className="border-t border-slate-200 bg-white">
            {/* Header */}
            <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-50 transition-colors"
            >
                <div className="flex items-center gap-2">
                    <svg
                        className={`w-4 h-4 text-slate-500 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
                    </svg>
                    <span className="font-medium text-slate-800">
                        Annotations ({filteredAnnotations.length})
                    </span>
                    {annotations.length !== filteredAnnotations.length && (
                        <span className="text-xs text-slate-500">
                            of {annotations.length}
                        </span>
                    )}
                </div>

                <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    {/* Filter by severity */}
                    <select
                        value={filterSeverity}
                        onChange={(e) => setFilterSeverity(e.target.value as Severity | 'all')}
                        className="text-xs border border-slate-200 rounded px-2 py-1 bg-white"
                    >
                        <option value="all">All Severities</option>
                        <option value="high">🔴 High</option>
                        <option value="medium">🟡 Medium</option>
                        <option value="low">🟢 Low</option>
                    </select>

                    {/* Toggle mine only */}
                    {currentAnnotatorId && (
                        <label className="flex items-center gap-1 text-xs text-slate-600 cursor-pointer">
                            <input
                                type="checkbox"
                                checked={showOnlyMine}
                                onChange={(e) => setShowOnlyMine(e.target.checked)}
                                className="rounded border-slate-300"
                            />
                            My Only
                        </label>
                    )}
                </div>
            </button>

            {/* Annotation List */}
            {isExpanded && (
                <div className="max-h-64 overflow-y-auto px-4 pb-4 space-y-2">
                    {filteredAnnotations.map((annotation) => {
                        const colors = severityColors[annotation.severity];
                        const isMine = annotation.annotator_id === currentAnnotatorId;

                        return (
                            <div
                                key={annotation.id}
                                className={`${colors.bg} border border-slate-200 rounded-lg p-3 group transition-all hover:shadow-sm`}
                            >
                                <div className="flex items-start gap-3">
                                    {/* Severity indicator */}
                                    <div className={`w-2 h-2 rounded-full mt-1.5 ${colors.dot}`} />

                                    {/* Content */}
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <button
                                                onClick={() => onSeek(annotation.global_timestamp)}
                                                className="text-xs font-mono text-slate-500 bg-slate-200 px-1.5 py-0.5 rounded hover:bg-slate-300 transition-colors"
                                            >
                                                {formatTime(annotation.global_timestamp)}
                                            </button>
                                            <span className={`text-xs font-medium ${colors.text}`}>
                                                {/* Category hidden as per request */}
                                            </span>
                                            <span className="text-xs text-slate-400">
                                                by {annotation.annotator_name}
                                            </span>
                                        </div>
                                        <p className="text-sm text-slate-700 break-words">
                                            {annotation.description}
                                        </p>
                                    </div>

                                    {/* Actions */}
                                    {isMine && (
                                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                            <button
                                                onClick={() => onEdit(annotation)}
                                                className="p-1 text-slate-400 hover:text-teal-600 transition-colors"
                                                title="Edit"
                                            >
                                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                                </svg>
                                            </button>
                                            <button
                                                onClick={() => handleDelete(annotation.id)}
                                                className="p-1 text-slate-400 hover:text-red-500 transition-colors"
                                                title="Delete"
                                            >
                                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                                </svg>
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
