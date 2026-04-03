import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'

interface AppState {
  theme: 'light' | 'dark'
  toggleTheme: () => void
  user: { name: string | null; role: string | null }
  setUser: (user: { name: string | null; role: string | null }) => void
}

export const useAppStore = create<AppState>()(
  devtools(
    persist(
      (set) => ({
        theme: 'light',
        toggleTheme: () => set((state) => ({ 
          theme: state.theme === 'light' ? 'dark' : 'light' 
        })),
        user: { name: null, role: null },
        setUser: (user) => set({ user }),
      }),
      {
        name: 'app-storage',
      }
    )
  )
)
