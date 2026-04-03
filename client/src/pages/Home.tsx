import React from 'react'

const Home: React.FC = () => {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center py-20 px-8">
      <h2 className="text-4xl font-extrabold mb-4 animate-fadeIn">
        Welcome to your <span className="text-primary tracking-tight">Structured Testimony</span> Dashboard
      </h2>
      <p className="max-w-2xl text-lg text-gray-600 dark:text-gray-400 mb-8 animate-fadeIn delay-100">
        A production-ready foundation designed for modularity, forensic analysis, and performance.
      </p>
      
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full max-w-5xl animate-fadeIn delay-200">
        {[
          { title: 'Modular Architecture', desc: 'Feature-based organization for scalability.', icon: '🏗️' },
          { title: 'Modern Stack', desc: 'Vite, React, TypeScript, and Tailwind CSS.', icon: '⚡' },
          { title: 'Type Safe', desc: 'Strict TypeScript configuration by default.', icon: '🛡️' }
        ].map((item, index) => (
          <div key={index} className="p-6 bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-2xl shadow-sm hover:shadow-md transition-shadow">
            <div className="text-3xl mb-3">{item.icon}</div>
            <h3 className="font-bold mb-2">{item.title}</h3>
            <p className="text-sm text-gray-500">{item.desc}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

export default Home
