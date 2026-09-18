import React from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { App } from './App'
import { HomePage } from './pages/HomePage'
import { RunPage, STAGES } from './pages/RunPage'
import './styles.css'

const router = createBrowserRouter([{
  path: '/', element: <App />, children: [
    { index: true, element: <HomePage /> },
    ...STAGES.map(s => ({ path: `runs/:id/${s.path}`, element: <RunPage stage={s.path} /> })),
  ],
}])

createRoot(document.getElementById('root')!).render(<React.StrictMode><RouterProvider router={router} /></React.StrictMode>)
