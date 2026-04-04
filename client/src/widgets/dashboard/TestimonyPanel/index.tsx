import React, { useState } from 'react';
import { useInvestigationStore } from '@/app/store/investigationStore';

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
        <span className="material-symbols-outlined text-xs text-primary">
          {isLoading ? 'sync' : 'fiber_manual_record'}
        </span>
      </div>
      <div className="space-y-4 overflow-y-auto flex-grow pr-2 custom-scrollbar">
        {isLoading && <p className="text-xs text-gray-500 font-label uppercase">Processing Narrative...</p>}
        
        {pipelineData?.events?.map((event, i) => (
          <div key={event.event_id || i} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="bg-primary text-on-primary text-[10px] px-2 font-black uppercase">
                {event.id?.startsWith('a') ? 'Witness A' : event.id?.startsWith('b') ? 'Witness B' : 'Extract'}
              </span>
              <span className="font-label text-[10px] text-gray-500">{event.time || 'Unknown Time'}</span>
            </div>
            <div className="bg-surface-container-highest p-3 text-sm font-body leading-relaxed">
              "{event.description}"
            </div>
            {event.placement_confidence === 'uncertain' && (
               <div className="bg-secondary-container/20 p-2 flex items-center gap-2 border-l-2 border-secondary">
                 <span className="material-symbols-outlined text-secondary text-sm">warning</span>
                 <span className="font-label text-[10px] text-secondary uppercase font-bold">Uncertain Element</span>
               </div>
            )}
          </div>
        ))}
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
            disabled={isLoading}
            className="absolute bottom-3 right-3 bg-primary text-on-primary p-2 flex items-center justify-center hover:brightness-110 active:scale-95 transition-all disabled:opacity-50">
            <span className="material-symbols-outlined">send</span>
          </button>
        </div>
      </div>
    </section>
  );
};
