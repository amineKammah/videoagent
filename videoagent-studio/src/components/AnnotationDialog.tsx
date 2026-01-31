'use client';

import { useState } from 'react';
import { Severity } from '@/lib/types';

interface AnnotationDialogProps {
    isOpen: boolean;
    onClose: () => void;
    onSubmit: (data: {
        category: string;
        description: string;
        severity: Severity;
    }) => void;
    sceneNumber: number;
    sceneTitle?: string;
    timestamp: number;
    globalTimestamp: number;
    // For editing existing annotation
    initialData?: {
        category: string;
        description: string;
        severity: Severity;
    };
    isEditing?: boolean;
}

const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
};

export function AnnotationDialog({
    isOpen,
    onClose,
    onSubmit,
    sceneNumber,
    sceneTitle,
    timestamp,
    globalTimestamp,
    initialData,
    isEditing = false,
}: AnnotationDialogProps) {
    const [description, setDescription] = useState(initialData?.description || '');
    const [severity, setSeverity] = useState<Severity>(initialData?.severity || 'medium');

    const handleSubmit = () => {
        if (!description.trim()) return;

        onSubmit({
            category: 'General',
            description: description.trim(),
            severity,
        });

        // Reset form
        setDescription('');
        setSeverity('medium');
    };

    const handleClose = () => {
        setDescription(initialData?.description || '');
        setSeverity(initialData?.severity || 'medium');
        onClose();
    };

    if (!isOpen) return null;

    const isValid = description.trim();

    return (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6 animate-slide-in relative">
                {/* Header */}
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold text-slate-800">
                        {isEditing ? 'Edit Annotation' : 'Add Annotation'}
                    </h3>
                    <button
                        onClick={handleClose}
                        className="text-slate-400 hover:text-slate-600 p-1"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                {/* Context info */}
                <div className="bg-slate-50 rounded-lg p-3 mb-4 flex items-center gap-3">
                    <div className="w-8 h-8 bg-teal-100 text-teal-700 rounded-lg flex items-center justify-center text-sm font-bold">
                        {sceneNumber}
                    </div>
                    <div>
                        <div className="text-sm font-medium text-slate-700">
                            Scene {sceneNumber}{sceneTitle ? `: ${sceneTitle.slice(0, 30)}...` : ''}
                        </div>
                        <div className="text-xs text-slate-500 font-mono">
                            📍 {formatTime(timestamp)} (Global: {formatTime(globalTimestamp)})
                        </div>
                    </div>
                </div>

                {/* Severity */}
                <div className="mb-4">
                    <label className="block text-sm font-medium text-slate-700 mb-2">
                        Severity
                    </label>
                    <div className="flex gap-4">
                        {(['low', 'medium', 'high'] as Severity[]).map((level) => (
                            <label
                                key={level}
                                className={`flex items-center gap-2 cursor-pointer px-3 py-2 rounded-lg border transition-colors ${severity === level
                                    ? level === 'high'
                                        ? 'bg-red-50 border-red-300 text-red-700'
                                        : level === 'medium'
                                            ? 'bg-yellow-50 border-yellow-300 text-yellow-700'
                                            : 'bg-green-50 border-green-300 text-green-700'
                                    : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300'
                                    }`}
                            >
                                <input
                                    type="radio"
                                    name="severity"
                                    value={level}
                                    checked={severity === level}
                                    onChange={() => setSeverity(level)}
                                    className="sr-only"
                                />
                                <span className={`w-2 h-2 rounded-full ${level === 'high' ? 'bg-red-500' :
                                    level === 'medium' ? 'bg-yellow-500' : 'bg-green-500'
                                    }`} />
                                <span className="text-sm font-medium capitalize">{level}</span>
                            </label>
                        ))}
                    </div>
                </div>

                {/* Description */}
                <div className="mb-4">
                    <label className="block text-sm font-medium text-slate-700 mb-1">
                        Description <span className="text-red-500">*</span>
                    </label>
                    <textarea
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        placeholder="Describe the issue in detail..."
                        className="w-full border border-slate-300 rounded-lg p-3 text-sm focus:ring-2 focus:ring-teal-500 focus:border-teal-500 outline-none h-24 resize-none"
                    />
                </div>

                {/* Actions */}
                <div className="flex justify-end gap-2">
                    <button
                        onClick={handleClose}
                        className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded-lg text-sm font-medium transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleSubmit}
                        disabled={!isValid}
                        className="px-4 py-2 bg-teal-600 hover:bg-teal-700 text-white rounded-lg text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                        {isEditing ? 'Save Changes' : 'Add Annotation'}
                    </button>
                </div>
            </div>
        </div>
    );
}
