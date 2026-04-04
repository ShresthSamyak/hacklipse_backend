import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { DemoService, PipelineResponse } from '@/shared/api/services';

interface InvestigationState {
  isActive: boolean;
  isLoading: boolean;
  error: string | null;
  pipelineData: PipelineResponse | null;
  
  // Actions
  loadSample: () => Promise<void>;
  runAnalysis: (text: string) => Promise<void>;
  reset: () => void;
}

export const useInvestigationStore = create<InvestigationState>()(
  devtools((set) => ({
    isActive: false,
    isLoading: false,
    error: null,
    pipelineData: null,

    loadSample: async () => {
      set({ isLoading: true, error: null });
      try {
        const data = await DemoService.getSample();
        set({ pipelineData: data, isActive: true, isLoading: false });
      } catch (err: any) {
        set({ error: err.message || 'Failed to load sample data', isLoading: false });
      }
    },

    runAnalysis: async (text: string) => {
      set({ isLoading: true, error: null });
      try {
        const data = await DemoService.runTextAnalysis(text);
        set({ pipelineData: data, isActive: true, isLoading: false });
      } catch (err: any) {
        set({ error: err.message || 'Failed to analyze text', isLoading: false });
      }
    },

    reset: () => set({ isActive: false, pipelineData: null, error: null }),
  }),
  { name: 'InvestigationStore' })
);
