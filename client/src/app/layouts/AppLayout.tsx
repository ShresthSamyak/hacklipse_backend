import React, { useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from '@/widgets/landing/Sidebar';
import { useInvestigationStore } from '@/app/store/investigationStore';

const Header: React.FC = () => {
  return (
    <header className="fixed top-0 w-full z-50 flex justify-between items-center px-6 h-16 bg-[#131314] dark:bg-[#131314] border-none">
      <div className="flex items-center gap-8">
        <span className="text-xl font-bold tracking-tighter text-[#a5e7ff] font-headline">Narrative Merge Engine</span>
        <nav className="hidden md:flex gap-6 items-center">
          <a className="font-['Space_Grotesk'] tracking-tight text-sm uppercase text-[#a5e7ff] font-bold border-b-2 border-[#a5e7ff] h-16 flex items-center transition-all duration-75" href="#">Case Selector</a>
          <a className="font-['Space_Grotesk'] tracking-tight text-sm uppercase text-gray-500 hover:bg-[#a5e7ff]/10 hover:text-white h-16 px-2 flex items-center transition-all duration-75" href="#">Mode Toggle</a>
        </nav>
      </div>
      <div className="flex items-center gap-4">
        <div className="relative flex items-center">
          <input className="bg-surface-container-low border-b border-outline-variant focus:border-primary focus:ring-0 text-xs font-label w-48 transition-all px-2 py-1 uppercase" placeholder="SEARCH DOSSIER..." type="text"/>
        </div>
        <button className="material-symbols-outlined text-[#a5e7ff] hover:bg-[#a5e7ff]/10 p-2 transition-all">account_circle</button>
      </div>
    </header>
  );
};

export const AppLayout: React.FC = () => {
  const { isActive, loadSample } = useInvestigationStore();

  useEffect(() => {
    if (!isActive) {
      loadSample();
    }
  }, [isActive, loadSample]);

  return (
    <div className="antialiased selection:bg-primary/30 selection:text-on-background min-h-screen bg-background text-on-background font-body flex">
      <Header />
      <Sidebar />
      <div className="flex-1 lg:ml-16 w-full max-w-[100vw]">
        <Outlet />
      </div>
    </div>
  );
};
