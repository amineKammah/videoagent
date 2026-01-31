import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { api } from '@/lib/api';
import { Annotation, AnnotationMetrics, ComparisonResult, CreateAnnotationRequest, Severity, UpdateAnnotationRequest } from '@/lib/types';

interface AnnotationStore {
    // State
    annotations: Annotation[];
    currentAnnotatorId: string;
    currentAnnotatorName: string;
    metrics: AnnotationMetrics | null;
    comparison: ComparisonResult | null;
    isLoading: boolean;
    error: string | null;

    // Actions
    loadAnnotations: (sessionId: string, annotatorId?: string) => Promise<void>;
    addAnnotation: (request: Omit<CreateAnnotationRequest, 'annotator_id' | 'annotator_name'>) => Promise<Annotation>;
    updateAnnotation: (id: string, updates: UpdateAnnotationRequest) => Promise<void>;
    deleteAnnotation: (id: string) => Promise<void>;
    setAnnotator: (id: string, name: string) => void;
    loadMetrics: (sessionId: string) => Promise<void>;
    loadComparison: (sessionId: string, annotatorIds?: string[]) => Promise<void>;
    clearAnnotations: () => void;
    getAnnotationsForTimestamp: (globalTimestamp: number, tolerance?: number) => Annotation[];
}

export const useAnnotationStore = create<AnnotationStore>()(
    persist(
        (set, get) => ({
            // Initial state
            annotations: [],
            currentAnnotatorId: '',
            currentAnnotatorName: '',
            metrics: null,
            comparison: null,
            isLoading: false,
            error: null,

            loadAnnotations: async (sessionId: string, annotatorId?: string) => {
                set({ isLoading: true, error: null });
                try {
                    const annotations = await api.listAnnotations(sessionId, annotatorId);
                    set({ annotations, isLoading: false });
                } catch (error) {
                    set({
                        error: error instanceof Error ? error.message : 'Failed to load annotations',
                        isLoading: false
                    });
                }
            },

            addAnnotation: async (request) => {
                const { currentAnnotatorId, currentAnnotatorName } = get();

                if (!currentAnnotatorId || !currentAnnotatorName) {
                    throw new Error('Annotator ID and name must be set before creating annotations');
                }

                const fullRequest: CreateAnnotationRequest = {
                    ...request,
                    annotator_id: currentAnnotatorId,
                    annotator_name: currentAnnotatorName,
                };

                set({ isLoading: true, error: null });
                try {
                    const annotation = await api.createAnnotation(fullRequest);
                    set(state => ({
                        annotations: [...state.annotations, annotation].sort(
                            (a, b) => a.global_timestamp - b.global_timestamp
                        ),
                        isLoading: false,
                    }));
                    return annotation;
                } catch (error) {
                    set({
                        error: error instanceof Error ? error.message : 'Failed to create annotation',
                        isLoading: false
                    });
                    throw error;
                }
            },

            updateAnnotation: async (id: string, updates: UpdateAnnotationRequest) => {
                set({ isLoading: true, error: null });
                try {
                    const updated = await api.updateAnnotation(id, updates);
                    set(state => ({
                        annotations: state.annotations.map(a =>
                            a.id === id ? updated : a
                        ),
                        isLoading: false,
                    }));
                } catch (error) {
                    set({
                        error: error instanceof Error ? error.message : 'Failed to update annotation',
                        isLoading: false
                    });
                    throw error;
                }
            },

            deleteAnnotation: async (id: string) => {
                set({ isLoading: true, error: null });
                try {
                    await api.deleteAnnotation(id);
                    set(state => ({
                        annotations: state.annotations.filter(a => a.id !== id),
                        isLoading: false,
                    }));
                } catch (error) {
                    set({
                        error: error instanceof Error ? error.message : 'Failed to delete annotation',
                        isLoading: false
                    });
                    throw error;
                }
            },

            setAnnotator: (id: string, name: string) => {
                set({ currentAnnotatorId: id, currentAnnotatorName: name });
            },

            loadMetrics: async (sessionId: string) => {
                try {
                    const metrics = await api.getAnnotationMetrics(sessionId);
                    set({ metrics });
                } catch (error) {
                    console.error('Failed to load annotation metrics:', error);
                }
            },

            loadComparison: async (sessionId: string, annotatorIds?: string[]) => {
                set({ isLoading: true, error: null });
                try {
                    const comparison = await api.compareAnnotations(sessionId, annotatorIds);
                    set({ comparison, isLoading: false });
                } catch (error) {
                    set({
                        error: error instanceof Error ? error.message : 'Failed to load comparison',
                        isLoading: false
                    });
                }
            },

            clearAnnotations: () => {
                set({ annotations: [], metrics: null, comparison: null });
            },

            getAnnotationsForTimestamp: (globalTimestamp: number, tolerance = 0.5) => {
                const { annotations } = get();
                return annotations.filter(
                    a => Math.abs(a.global_timestamp - globalTimestamp) <= tolerance
                );
            },
        }),
        {
            name: 'annotation-store',
            partialize: (state) => ({
                currentAnnotatorId: state.currentAnnotatorId,
                currentAnnotatorName: state.currentAnnotatorName,
            }),
        }
    )
);
