import { AnnotationMetrics as MetricsType } from '@/lib/types';

interface AnnotationMetricsProps {
    metrics: MetricsType;
    sessionName?: string;
    onClose: () => void;
}

export function AnnotationMetrics({ metrics, sessionName, onClose }: AnnotationMetricsProps) {
    const totalAnnotations = metrics.total_annotations;
    const severityData = metrics.by_severity;
    const categoryData = metrics.by_category;

    // Sort categories by count desc
    const sortedCategories = Object.entries(categoryData).sort(([, a], [, b]) => b - a);

    return (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center backdrop-blur-sm p-4 animate-fade-in">
            <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl overflow-hidden flex flex-col max-h-[90vh]">

                {/* Header */}
                <div className="p-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
                    <div>
                        <h2 className="text-xl font-bold text-slate-800">Metrics Dashboard</h2>
                        {sessionName && (
                            <p className="text-sm text-slate-500 mt-1">Session: {sessionName}</p>
                        )}
                    </div>

                    <button
                        onClick={onClose}
                        className="p-2 hover:bg-slate-200 rounded-full transition-colors text-slate-500"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                    </button>
                </div>

                {/* Content Area */}
                <div className="overflow-y-auto flex-1 p-6 bg-slate-50/30">
                    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
                        {/* Key Stats Cards */}
                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                            <div className="bg-blue-50 rounded-xl p-4 border border-blue-100">
                                <p className="text-xs font-semibold text-blue-600 uppercase tracking-wider mb-1">Total</p>
                                <p className="text-3xl font-bold text-blue-900">{totalAnnotations}</p>
                            </div>
                            <div className="bg-green-50 rounded-xl p-4 border border-green-100">
                                <p className="text-xs font-semibold text-green-600 uppercase tracking-wider mb-1">Faultless Scenes</p>
                                <p className="text-3xl font-bold text-green-900">{metrics.faultless_scenes} <span className="text-sm font-normal text-green-700">/ {metrics.total_scenes}</span></p>
                            </div>
                            <div className="bg-amber-50 rounded-xl p-4 border border-amber-100">
                                <p className="text-xs font-semibold text-amber-600 uppercase tracking-wider mb-1">Scenes Modified</p>
                                <p className="text-3xl font-bold text-amber-900">{Object.keys(metrics.by_scene).length}</p>
                            </div>
                            <div className="bg-purple-50 rounded-xl p-4 border border-purple-100">
                                <p className="text-xs font-semibold text-purple-600 uppercase tracking-wider mb-1">Avg per Scene</p>
                                <p className="text-3xl font-bold text-purple-900">
                                    {metrics.total_scenes > 0
                                        ? (totalAnnotations / metrics.total_scenes).toFixed(1)
                                        : '0.0'}
                                </p>
                            </div>
                        </div>

                        {/* Breakdown Graphs */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">

                            {/* Severity Stats */}
                            <div>
                                <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-4 border-b border-slate-100 pb-2">By Severity</h3>
                                <div className="space-y-4">
                                    {[
                                        { label: 'High', count: severityData.high || 0, color: 'bg-red-500', text: 'text-red-700', bg: 'bg-red-50' },
                                        { label: 'Medium', count: severityData.medium || 0, color: 'bg-yellow-400', text: 'text-yellow-700', bg: 'bg-yellow-50' },
                                        { label: 'Low', count: severityData.low || 0, color: 'bg-green-500', text: 'text-green-700', bg: 'bg-green-50' }
                                    ].map(item => (
                                        <div key={item.label}>
                                            <div className="flex justify-between text-sm mb-1">
                                                <span className={`font-medium ${item.text}`}>{item.label}</span>
                                                <span className="text-slate-600">{item.count}</span>
                                            </div>
                                            <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
                                                <div
                                                    className={`h-full ${item.color}`}
                                                    style={{ width: `${totalAnnotations > 0 ? (item.count / totalAnnotations) * 100 : 0}%` }}
                                                />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* Top Categories */}
                            <div>
                                <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-4 border-b border-slate-100 pb-2">Top Issues</h3>
                                {sortedCategories.length === 0 ? (
                                    <p className="text-sm text-slate-400 italic">No categorized issues yet.</p>
                                ) : (
                                    <div className="space-y-3">
                                        {sortedCategories.slice(0, 5).map(([category, count]) => (
                                            <div key={category} className="flex items-center justify-between group">
                                                <div className="flex items-center gap-3">
                                                    <div className="w-1.5 h-1.5 rounded-full bg-slate-300 group-hover:bg-teal-500 transition-colors"></div>
                                                    <span className="text-sm text-slate-600 font-medium capitalize truncate max-w-[180px]" title={category}>{category}</span>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    <div className="w-24 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                                                        <div
                                                            className="h-full bg-slate-400 group-hover:bg-teal-500 transition-colors"
                                                            style={{ width: `${totalAnnotations > 0 ? (count / totalAnnotations) * 100 : 0}%` }}
                                                        />
                                                    </div>
                                                    <span className="text-xs text-slate-500 w-4 text-right">{count}</span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>

                {/* Footer */}
                <div className="p-4 bg-slate-50 border-t border-slate-100 text-center">
                    <button
                        onClick={onClose}
                        className="text-sm text-slate-500 hover:text-slate-800 font-medium transition-colors"
                    >
                        Close Dashboard
                    </button>
                </div>
            </div>
        </div>
    );
}
