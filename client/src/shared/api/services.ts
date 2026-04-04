import { apiClient } from './client';

export interface PipelineResponse {
  pipeline_id: string;
  transcript: string;
  events: any[]; // Or define more specific interface
  timeline: {
    confirmed_sequence?: any[];
    probable_sequence?: any[];
    uncertain_events?: any[];
    event_count?: number;
    confidence_summary?: any;
    temporal_links?: any[];
    metadata?: any;
  };
  conflicts: {
    confirmed_events?: any[];
    conflicts?: any[];
    uncertain_events?: any[];
    next_question?: {
      question: string;
      reason: string;
    };
    conflict_count?: number;
    has_conflicts?: boolean;
  };
  status: string;
  errors: string[];
}

export const DemoService = {
  getSample: async (): Promise<PipelineResponse> => {
    const { data } = await apiClient.get<PipelineResponse>('/demo/sample');
    return data;
  },
  
  runTextAnalysis: async (text: string): Promise<PipelineResponse> => {
    const { data } = await apiClient.post<PipelineResponse>('/demo/run-text', {
      text,
      demo_mode: true,
      fast_preview: false,
    });
    return data;
  }
};
