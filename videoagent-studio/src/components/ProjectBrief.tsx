'use client';

import { useState } from 'react';
import { useSessionStore } from '@/store/session';
import { api } from '@/lib/api';

export function ProjectBrief() {
    const session = useSessionStore(state => state.session);
    const customerDetails = useSessionStore(state => state.customerDetails);
    const setCustomerDetails = useSessionStore(state => state.setCustomerDetails);
    const setScenes = useSessionStore(state => state.setScenes);
    const isProcessing = useSessionStore(state => state.isProcessing);

    const [isDrafting, setIsDrafting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isCollapsed, setIsCollapsed] = useState(false);

    const handleDraftStoryboard = async () => {
        if (!session || !customerDetails.trim()) return;

        setIsDrafting(true);
        setError(null);

        try {
            const response = await api.draftStoryboard(session.id, customerDetails);
            setScenes(response.scenes);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to draft storyboard');
        } finally {
            setIsDrafting(false);
        }
    };

    return (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm mb-4 overflow-hidden">
            {/* Header - Always visible, clickable to collapse */}
            <button
                onClick={() => setIsCollapsed(!isCollapsed)}
                className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-50 transition-colors text-left"
            >
                <div>
                    <h3 className="font-semibold text-slate-800">Project Brief</h3>
                    {isCollapsed && customerDetails && (
                        <p className="text-xs text-slate-500 mt-0.5 truncate max-w-md">
                            {customerDetails.substring(0, 60)}{customerDetails.length > 60 ? '...' : ''}
                        </p>
                    )}
                </div>
                <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    className={`w-4 h-4 text-slate-400 transition-transform ${isCollapsed ? '' : 'rotate-180'}`}
                >
                    <path
                        fillRule="evenodd"
                        d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                        clipRule="evenodd"
                    />
                </svg>
            </button>

            {/* Collapsible content */}
            {!isCollapsed && (
                <div className="px-4 pb-4 border-t border-slate-100">
                    <p className="text-xs text-slate-500 mb-3 pt-3">
                        Describe the customer situation and desired outcome
                    </p>

                    <textarea
                        value={customerDetails}
                        onChange={(e) => setCustomerDetails(e.target.value)}
                        placeholder="Enter customer details, pain points, and what the video should accomplish..."
                        className="w-full rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 text-sm 
                       placeholder:text-slate-400 focus:border-teal-500 focus:bg-white focus:outline-none 
                       focus:ring-2 focus:ring-teal-500/20 resize-none transition-all duration-200"
                        rows={4}
                        disabled={isDrafting || isProcessing}
                    />

                    {error && (
                        <p className="text-xs text-red-600 mt-2">{error}</p>
                    )}

                    <div className="flex gap-2 mt-3">
                        <button
                            onClick={handleDraftStoryboard}
                            disabled={!session || !customerDetails.trim() || isDrafting || isProcessing}
                            className="px-4 py-2 bg-teal-600 text-white text-sm font-medium rounded-lg
                         hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed
                         transition-colors duration-200"
                        >
                            {isDrafting ? 'Drafting...' : 'Draft Storyboard'}
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
