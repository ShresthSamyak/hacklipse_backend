import React from 'react'
import { Outlet } from 'react-router-dom'

export const MainLayout: React.FC = () => {
  return (
    <div className="flex flex-col min-h-screen">
      <header className="py-4 px-6 border-b border-gray-200 dark:border-gray-800">
        <h1 className="text-xl font-bold bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent">
          Forensic Dashboard
        </h1>
      </header>
      <main className="flex-1 container mx-auto p-6 animate-fadeIn">
        <Outlet />
      </main>
      <footer className="py-4 px-6 border-t border-gray-200 dark:border-gray-800 text-center text-sm text-gray-500">
        Powered by Structured Testimony
      </footer>
    </div>
  )
}
