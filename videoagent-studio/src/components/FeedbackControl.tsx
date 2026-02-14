import { useState, useEffect } from 'react';
import { Feedback, FeedbackRating, UpsertFeedbackRequest } from '@/lib/types';
import { api } from '@/lib/api';

interface FeedbackControlProps {
    sessionId: string;
    targetType: 'storyboard' | 'scene' | 'video_brief';
    targetId: string | null;
    initialFeedback: Feedback | null;
    onFeedbackUpdate: (feedback: Feedback) => void;
    className?: string;
    variant?: 'minimal' | 'full'; // minimal for SceneCard, full for others
}

export function FeedbackControl({
    sessionId,
    targetType,
    targetId,
    initialFeedback,
    onFeedbackUpdate,
    className = '',
    variant = 'full'
}: FeedbackControlProps) {
    const [rating, setRating] = useState<FeedbackRating | null>(initialFeedback?.rating ?? null);
    const [comment, setComment] = useState<string>(initialFeedback?.comment ?? '');
    const [isSaving, setIsSaving] = useState(false);
    const [showCommentInput, setShowCommentInput] = useState(!!initialFeedback?.comment || false);

    useEffect(() => {
        setRating(initialFeedback?.rating ?? null);
        setComment(initialFeedback?.comment ?? '');
        setShowCommentInput(!!initialFeedback?.comment);
    }, [initialFeedback]);

    const handleRate = async (newRating: FeedbackRating) => {
        // If clicking the same rating, toggle it off (delete?) or just keep it? 
        // Plan says "upsert", implying we always value what is clicked. 
        // But usually clicking active toggle deselects. Let's assume re-clicking just confirms for now, 
        // or we implementation "toggle off" logic if needed. 
        // For now, simple set.

        const isNew = rating !== newRating;
        setRating(newRating);
        if (newRating === 'down') {
            setShowCommentInput(true);
        } else {
            // Optional: hide comment input if switching to up? 
            // Better to keep it if user already wrote something.
        }

        // Auto-save rating change immediately
        await submitFeedback(newRating, comment);
    };

    const submitFeedback = async (r: FeedbackRating, c: string | null) => {
        setIsSaving(true);
        try {
            const req: UpsertFeedbackRequest = {
                target_type: targetType,
                target_id: targetId,
                rating: r,
                comment: c
            };
            const updated = await api.upsertFeedback(sessionId, req);
            onFeedbackUpdate(updated);
        } catch (error) {
            console.error('Failed to submit feedback:', error);
            // Revert state on error? For now just log.
        } finally {
            setIsSaving(false);
        }
    };

    const handleCommentSave = async () => {
        if (rating) {
            await submitFeedback(rating, comment);
        }
    };

    // Minimal variant for SceneCard (just icons, maybe read-only or simple toggle)
    // Actually plan says "SceneCard — Add a small inline thumbs up/down indicator... show the appropriate thumb icon highlighted"
    // So distinct from the interactive control in modal.
    // This component is mainly for SceneModal and Storyboard footer.

    const getTargetLabel = () => {
        switch (targetType) {
            case 'scene': return 'scene';
            case 'storyboard': return 'storyboard';
            case 'video_brief': return 'video brief';
            default: return 'content';
        }
    };

    if (variant === 'minimal') {
        return (
            <div className={`flex flex-col items-end gap-2 ${className} relative`}>
                <div className="flex gap-1 bg-white/50 backdrop-blur-sm p-1 rounded-full border border-slate-200 shadow-sm">
                    <button
                        onClick={() => handleRate('up')}
                        disabled={isSaving}
                        className={`p-1.5 rounded-full transition-all text-lg leading-none ${rating === 'up'
                            ? 'bg-green-100 ring-1 ring-green-300 scale-110'
                            : 'hover:bg-slate-100 hover:scale-110 grayscale opacity-60 hover:grayscale-0 hover:opacity-100'
                            }`}
                        title="Thumbs Up"
                    >
                        👍
                    </button>

                    <div className="w-px bg-slate-200 my-1" />

                    <button
                        onClick={() => handleRate('down')}
                        disabled={isSaving}
                        className={`p-1.5 rounded-full transition-all text-lg leading-none ${rating === 'down'
                            ? 'bg-red-100 ring-1 ring-red-300 scale-110'
                            : 'hover:bg-slate-100 hover:scale-110 grayscale opacity-60 hover:grayscale-0 hover:opacity-100'
                            }`}
                        title="Thumbs Down"
                    >
                        👎
                    </button>
                </div>

                {rating && (
                    <button
                        onClick={() => setShowCommentInput(!showCommentInput)}
                        className="text-[10px] font-medium text-slate-400 hover:text-teal-600 uppercase tracking-wider pr-1"
                    >
                        {showCommentInput ? 'Close' : (comment ? 'Edit Comment' : 'Add Comment')}
                    </button>
                )}

                {showCommentInput && (
                    <div className="absolute bottom-full right-0 mb-2 w-64 bg-white p-3 rounded-lg border border-slate-200 shadow-xl animate-in slide-in-from-bottom-2 fade-in duration-200 z-10">
                        <textarea
                            value={comment}
                            onChange={(e) => setComment(e.target.value)}
                            placeholder="Tell us more..."
                            className="w-full text-xs p-2 border border-slate-200 rounded-md focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none min-h-[60px] resize-none text-slate-700"
                            autoFocus
                        />
                        <div className="flex justify-between items-center mt-2">
                            <button
                                onClick={() => setShowCommentInput(false)}
                                className="text-xs text-slate-400 hover:text-slate-600"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleCommentSave}
                                disabled={isSaving}
                                className="text-xs px-2.5 py-1 bg-slate-800 text-white rounded hover:bg-slate-700 transition-colors disabled:opacity-50"
                            >
                                {isSaving ? 'Saving...' : 'Save'}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        );
    }

    return (
        <div className={`p-4 bg-slate-50 rounded-lg border border-slate-200 ${className}`}>
            <div className="flex items-center gap-4">
                <span className="text-sm font-medium text-slate-600">
                    Was this {getTargetLabel()} helpful?
                </span>

                <div className="flex gap-2">
                    <button
                        onClick={() => handleRate('up')}
                        disabled={isSaving}
                        className={`p-2 rounded-full transition-all ${rating === 'up'
                            ? 'bg-green-100 text-green-700 ring-2 ring-green-500 ring-offset-1'
                            : 'hover:bg-slate-200 text-slate-400 hover:text-green-600'
                            }`}
                        title="Thumbs Up"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                            <path d="M1 8.25a1.25 1.25 0 1 1 2.5 0v7.5a1.25 1.25 0 1 1-2.5 0v-7.5ZM11 3V1.7c0-.268.14-.526.395-.607A2 2 0 0 1 14 3c0 .995-.182 1.948-.514 2.826-.204.54.166 1.174.744 1.174h2.52c1.243 0 2.261 1.01 2.261 2.251v5.753c0 1.24-1.018 2.251-2.261 2.251h-6.83a2 2 0 0 1-1.396-.519l-3.674-2.25a1.25 1.25 0 0 1 .6 2.05l-3.33 2.155a.75.75 0 0 1-1.16-.628l-.34-4.86A3.251 3.251 0 0 1 5 6.75h1.25v2.247l3.655-2.274a2 2 0 0 1 1.345-.523h4.636l-1.03-3.07a.75.75 0 0 0-.712-.511L11 3Z" />
                            <path d="M11 3v2c0 .54-.188 1.096-.514 1.62-.204.54.166 1.174.744 1.174h2.52c1.243 0 2.261 1.01 2.261 2.251v4.5A2.251 2.251 0 0 1 13.75 17h-4.398a2.25 2.25 0 0 1-1.928-1.09l-2.023-3.414A.75.75 0 0 0 4.75 12H5V7.495a.75.75 0 0 1 .75-.75h.923c.59 0 1.144-.242 1.549-.66L11 3Z" />
                            {/* Simple thumbs up path replacement for clearer icon if needed, but using HeroIcons style path */}
                            <path d="M7 11.333a4.333 4.333 0 0 1 0-8.666h.774l-.457-2.083a1 1 0 0 1 1.095-1.217l3.865.552a1 1 0 0 1 .75.603l1.802 4.145h3.838a2 2 0 0 1 2 2v5.333a2 2 0 0 1-2 2H11.5a3.99 3.99 0 0 1-3.003-1.365l-1.497 1.497v-2.8z" style={{ display: 'none' }} />
                            <path d="M11.986 3H12a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h6.986zM11.986 3V1.7c0-.268.14-.526.395-.607A2 2 0 0114 3c0 .995-.182 1.948-.514 2.826-.204.54.166 1.174.744 1.174h2.52c1.243 0 2.261 1.01 2.261 2.251v5.753c0 1.24-1.018 2.251-2.261 2.251h-6.83a2 2 0 01-1.396-.519l-3.674-2.25a1.25 1.25 0 01.6 2.05l-3.33 2.155a.75.75 0 01-1.16-.628l-.34-4.86A3.251 3.251 0 015 6.75h1.25v2.247l3.655-2.274a2 2 0 011.345-.523h4.636l-1.03-3.07a.75.75 0 00-.712-.511L11 3z" style={{ display: 'none' }} />
                        </svg>
                    </button>

                    <button
                        onClick={() => handleRate('down')}
                        disabled={isSaving}
                        className={`p-2 rounded-full transition-all ${rating === 'down'
                            ? 'bg-red-100 text-red-700 ring-2 ring-red-500 ring-offset-1'
                            : 'hover:bg-slate-200 text-slate-400 hover:text-red-600'
                            }`}
                        title="Thumbs Down"
                    >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                            <path d="M18.905 12.75a1.25 1.25 0 0 1-2.5 0v-7.5a1.25 1.25 0 1 1 2.5 0v7.5ZM8.905 17v1.3c0 .268-.14.526-.395.607A2 2 0 0 1 5.905 17c0-.995.182-1.948.514-2.826.204-.54-.166-1.174-.744-1.174h-2.52c-1.243 0-2.261-1.01-2.261-2.251v-5.753c0-1.24 1.018-2.251 2.261-2.251h6.83A2 2 0 0 1 11.381 3.26l3.674 2.25a1.25 1.25 0 0 1-.6-2.05l3.33-2.155a.75.75 0 0 1 1.16.628l.34 4.86a3.251 3.251 0 0 1-1.924 3.957h-1.25v-2.247l-3.655 2.274a2 2 0 0 1-1.345.523h-4.636l1.03 3.07a.75.75 0 0 0 .712.511l.104-.005Z" />
                        </svg>
                    </button>
                </div>

                {rating && (
                    <button
                        onClick={() => setShowCommentInput(!showCommentInput)}
                        className="text-xs text-slate-500 hover:text-teal-600 underline decoration-dotted"
                    >
                        {showCommentInput ? 'Hide comment' : (comment ? 'Edit comment' : 'Add comment')}
                    </button>
                )}
            </div>

            {showCommentInput && (
                <div className="mt-3 animate-in slide-in-from-top-2 fade-in duration-200">
                    <textarea
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                        placeholder="Tell us more about your feedback (optional)..."
                        className="w-full text-sm p-2 border border-slate-200 rounded-md focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none min-h-[60px]"
                    />
                    <div className="flex justify-end mt-2">
                        <button
                            onClick={handleCommentSave}
                            disabled={isSaving}
                            className="text-xs px-3 py-1.5 bg-slate-800 text-white rounded hover:bg-slate-700 transition-colors disabled:opacity-50"
                        >
                            {isSaving ? 'Saving...' : 'Save Comment'}
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
