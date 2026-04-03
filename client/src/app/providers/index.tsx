import React, { ReactNode } from 'react'

interface AppProvidersProps {
  children: ReactNode
}

export const AppProviders: React.FC<AppProvidersProps> = ({ children }) => {
  return (
    <>
      {children}
    </>
  )
}
