import { ComparisonResult, Annotation } from '@/lib/types';
import { useState } from 'react';

interface AnnotationComparisonProps {
    comparison: ComparisonResult | null;
    isLoading: boolean;
    onSeek: (time: number) => void;
    onEdit: (annotation: Annotation) => void;
    onDelete: (id: string) => Promise<void>;
    onResolve: (ids: string[]) => Promise<void>;
}

export function AnnotationComparison({
    comparison,
    isLoading,
    onSeek,
    onEdit,
    onDelete,
    onResolve
}: AnnotationComparisonProps) {
    const [processingClusterId, setProcessingClusterId] = useState<string | null>(null);

    const handleKeepAll = async (clusterId: string, annotations: Annotation[]) => {
        setProcessingClusterId(clusterId);
        try {
            await onResolve(annotations.map(a => a.id));
        } finally {
            setProcessingClusterId(null);
        }
    };

    const handleKeepOne = async (clusterId: string, keepId: string, allAnnotations: Annotation[]) => {
        setProcessingClusterId(clusterId);
        try {
            const toDelete = allAnnotations.filter(a => a.id !== keepId);
            // Delete others
            for (const ann of toDelete) {
                await onDelete(ann.id);
            }
            // Resolve kept
            await onResolve([keepId]);
        } finally {
            setProcessingClusterId(null);
        }
    };

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center h-64 text-slate-400">
                <svg className="w-8 h-8 mb-4 animate-spin text-teal-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <p>Analyzing conflicts...</p>
            </div>
        );
    }

    if (!comparison) {
        return <div className="p-8 text-center text-slate-400">No comparison data available</div>;
    }

    const { stats, clusters, annotators } = comparison;

    return (
        <div className="h-full flex flex-col bg-slate-50">
            {/* Summary Header */}
            <div className="bg-white border-b border-slate-200 p-4">
                <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Comparison Summary</h3>

                <div className="grid grid-cols-3 gap-2 mb-4">
                    <div className="bg-red-50 rounded-lg p-2 border border-red-100 text-center">
                        <p className="text-xl font-bold text-red-900 leading-tight">{stats.conflicts}</p>
                        <p className="text-[10px] font-semibold text-red-600 uppercase">Conflicts</p>
                    </div>
                    <div className="bg-teal-50 rounded-lg p-2 border border-teal-100 text-center">
                        <p className="text-xl font-bold text-teal-900 leading-tight">{stats.agreements}</p>
                        <p className="text-[10px] font-semibold text-teal-600 uppercase">Agreements</p>
                    </div>
                    <div className="bg-blue-50 rounded-lg p-2 border border-blue-100 text-center">
                        <p className="text-xl font-bold text-blue-900 leading-tight">{stats.unique_annotations}</p>
                        <p className="text-[10px] font-semibold text-blue-600 uppercase">Unique</p>
                    </div>
                </div>

                <div className="flex flex-wrap gap-1">
                    <span className="text-xs text-slate-400 mr-1">Annotators:</span>
                    {annotators.length === 0 ? <span className="text-slate-400 text-xs">None</span> :
                        annotators.map(a => (
                            <span key={a} className="inline-block px-1.5 py-0.5 bg-slate-100 text-slate-600 rounded text-[10px] border border-slate-200 truncate max-w-[80px]" title={a}>{a}</span>
                        ))
                    }
                </div>
            </div>

            {/* Clusters List */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {clusters.length === 0 ? (
                    <div className="text-center py-8 text-slate-400">
                        <p className="text-sm">No annotation clusters found.</p>
                    </div>
                ) : (
                    clusters.map((cluster) => (
                        <div
                            key={cluster.id}
                            className={`bg-white rounded-lg border shadow-sm transition-all ${cluster.status === 'conflict' ? 'border-red-200 ring-1 ring-red-100' :
                                cluster.status === 'agreement' ? 'border-teal-200' :
                                    'border-slate-200'
                                } ${processingClusterId === cluster.id ? 'opacity-50 pointer-events-none' : ''}`}
                        >
                            <div
                                onClick={() => onSeek(cluster.center_timestamp)}
                                className={`px-3 py-2 border-b flex items-center justify-between cursor-pointer ${cluster.status === 'conflict' ? 'bg-red-50/50 hover:bg-red-50' :
                                    cluster.status === 'agreement' ? 'bg-teal-50/50 hover:bg-teal-50' :
                                        'bg-slate-50/50 hover:bg-slate-100'
                                    }`}>
                                <div className="flex items-center gap-2">
                                    <span className={`w-2 h-2 rounded-full ${cluster.status === 'conflict' ? 'bg-red-500' :
                                        cluster.status === 'agreement' ? 'bg-teal-500' :
                                            'bg-blue-400'
                                        }`} />
                                    <span className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded tracking-wide ${cluster.status === 'conflict' ? 'bg-red-100 text-red-600' :
                                            cluster.status === 'unique' ? 'bg-blue-100 text-blue-600' :
                                                'bg-teal-100 text-teal-600'
                                        }`}>
                                        {cluster.status}
                                    </span>
                                    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${cluster.annotator_count < cluster.total_annotators
                                            ? 'bg-amber-50 text-amber-700 border-amber-200'
                                            : 'bg-slate-50 text-slate-500 border-slate-200'
                                        }`}>
                                        {cluster.annotator_count}/{cluster.total_annotators} Annotators
                                    </span>
                                </div>
                                <div className="flex items-center gap-2">
                                    <span className="text-xs text-slate-500 font-mono bg-white px-1.5 rounded border border-slate-100">
                                        {new Date(cluster.center_timestamp * 1000).toISOString().substr(14, 5)}
                                    </span>
                                    {/* Resolve All Button for Conflicts */}
                                    {cluster.status === 'conflict' && (
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleKeepAll(cluster.id, cluster.annotations);
                                            }}
                                            className="text-[10px] bg-white border border-slate-300 hover:bg-slate-50 text-slate-600 px-2 py-0.5 rounded shadow-sm"
                                        >
                                            Keep All
                                        </button>
                                    )}
                                </div>
                            </div>

                            <div className="p-3 space-y-2">
                                {cluster.annotations.map(ann => {
                                    const isRejected = ann.rejected;
                                    return (
                                        <div key={ann.id} className={`text-xs border-l-2 pl-2 group relative -mx-2 px-2 py-1 rounded transition-colors ${isRejected ? 'border-slate-200 bg-slate-50/50 opacity-60' :
                                            ann.resolved ? 'border-green-300 hover:bg-slate-50' :
                                                'border-slate-100 hover:bg-slate-50'
                                            }`}>
                                            <div className="flex justify-between items-start mb-0.5">
                                                <div className="flex items-center gap-2">
                                                    <span className={`font-medium ${isRejected ? 'line-through text-slate-400' : 'text-slate-700'}`}>{ann.annotator_name}</span>
                                                    {ann.resolved && !isRejected && <span className="text-green-500 text-[10px]">✓</span>}
                                                    {isRejected && <span className="text-slate-400 text-[10px] italic">(Rejected)</span>}
                                                </div>
                                                {!isRejected && (
                                                    <div className="flex items-center gap-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity">
                                                        {cluster.status === 'conflict' && !ann.resolved && (
                                                            <button
                                                                onClick={() => handleKeepOne(cluster.id, ann.id, cluster.annotations)}
                                                                title="Keep only this one"
                                                                className="p-1 hover:bg-green-100 text-slate-400 hover:text-green-600 rounded bg-white shadow-sm border border-slate-100"
                                                            >
                                                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
                                                            </button>
                                                        )}
                                                        <button
                                                            onClick={() => onEdit(ann)}
                                                            title="Edit"
                                                            className="p-1 hover:bg-blue-100 text-slate-400 hover:text-blue-600 rounded bg-white shadow-sm border border-slate-100"
                                                        >
                                                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                                                        </button>
                                                        <button
                                                            onClick={() => onDelete(ann.id)}
                                                            title="Reject"
                                                            className="p-1 hover:bg-red-100 text-slate-400 hover:text-red-600 rounded bg-white shadow-sm border border-slate-100"
                                                        >
                                                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                                        </button>
                                                    </div>
                                                )}
                                            </div>
                                            <div className="flex items-center gap-1 mb-1">
                                                <span className={`px-1 rounded text-[9px] uppercase tracking-wider ${isRejected ? 'bg-slate-100 text-slate-400' :
                                                    ann.severity === 'high' ? 'bg-red-100 text-red-700' :
                                                        ann.severity === 'medium' ? 'bg-yellow-100 text-yellow-800' :
                                                            'bg-green-100 text-green-700'
                                                    }`}>
                                                    {ann.severity}
                                                </span>
                                                <span className={`text-[10px] font-medium ${isRejected ? 'text-slate-400 line-through' : 'text-slate-500'}`}>{ann.category}</span>
                                            </div>
                                            <p className={`text-slate-500 line-clamp-2 ${isRejected ? 'line-through opacity-75' : ''}`}>{ann.description}</p>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
