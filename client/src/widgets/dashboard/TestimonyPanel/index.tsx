import React, { useState } from 'react';
import { useInvestigationStore } from '@/app/store/investigationStore';
import { ExtractedEvent } from '@/shared/api/types';

export const TestimonyPanel: React.FC = () => {
  const { pipelineData, runAnalysis, isLoading } = useInvestigationStore();
  const [inputText, setInputText] = useState('');

  const handleAnalyze = async () => {
    if (!inputText.trim()) return;
    await runAnalysis(inputText);
    setInputText('');
  };

  return (
    <section className="col-span-3 bg-surface-container-low flex flex-col p-4 border-r border-outline-variant/10">
      <div className="flex items-center justify-between mb-6">
        <h3 className="font-headline text-xs font-bold uppercase tracking-widest text-primary">Testimony Streams</h3>
        <span className={`material-symbols-outlined text-xs ${isLoading ? 'animate-spin text-tertiary' : 'text-primary'}`}>
          {isLoading ? 'sync' : 'fiber_manual_record'}
        </span>
      </div>
      <div className="space-y-4 overflow-y-auto flex-grow pr-2 custom-scrollbar">
        {isLoading && (
          <div className="flex flex-col items-center justify-center h-32 opacity-50">
             <span className="material-symbols-outlined animate-spin text-2xl mb-2">sync</span>
             <p className="text-[10px] font-label uppercase tracking-tighter">Processing Narrative Engine...</p>
          </div>
        )}
        
        {!isLoading && pipelineData?.events?.map((event: ExtractedEvent, i: number) => (
          <div key={event.id || i} className="space-y-2 animate-in fade-in slide-in-from-left-4 duration-500" style={{ animationDelay: `${i * 100}ms` }}>
            <div className="flex items-center gap-2">
              <span className="bg-primary text-on-primary text-[10px] px-2 font-black uppercase">
                {event.id?.startsWith('evt-') ? 'Analysis' : 'Witness'}
              </span>
              <span className="font-label text-[10px] text-gray-400">{event.time || 'Approximate Time'}</span>
            </div>
            <div className="bg-surface-container-highest p-3 text-sm font-body leading-relaxed border-l-2 border-primary/20">
              "{event.description}"
            </div>
            <div className="flex gap-1">
              {event.actors?.map((actor, idx) => (
                <span key={idx} className="text-[8px] font-label uppercase bg-surface-variant px-1 text-gray-400">@{actor}</span>
              ))}
            </div>
          </div>
        ))}

        {!isLoading && !pipelineData?.events?.length && (
          <div className="flex flex-col items-center justify-center h-full opacity-20 grayscale">
            <span className="material-symbols-outlined text-4xl mb-2">history_edu</span>
            <p className="text-[10px] font-label uppercase text-center px-8">No testimonies ingested for this dossier yet.</p>
          </div>
        )}
      </div>
      {/* Input Area */}
      <div className="mt-4 pt-4 border-t border-outline-variant/20">
        <div className="relative">
          <textarea 
            className="w-full bg-surface-container-lowest border-b border-outline-variant text-sm p-3 focus:outline-none focus:border-primary transition-all resize-none min-h-[100px] font-body" 
            placeholder="Log manual testimony or cross-examine..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            disabled={isLoading}
          ></textarea>
          <button 
            onClick={handleAnalyze}
            disabled={isLoading || !inputText.trim()}
            className="absolute bottom-3 right-3 bg-primary text-on-primary p-2 flex items-center justify-center hover:brightness-110 active:scale-95 transition-all disabled:opacity-50">
            <span className="material-symbols-outlined">
              {isLoading ? 'hourglass_top' : 'send'}
            </span>
          </button>
        </div>
      </div>
    </section>
  );
};
