import React from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { App } from './App'
import './i18n'
import { HomePage } from './pages/HomePage'
import { ProjectsPage } from './pages/ProjectsPage'
import { CouncilPage, STAGES, stagePath } from './pages/CouncilPage'
import './styles.css'

const router = createBrowserRouter([{
  path: '/', element: <App />, children: [
    { index: true, element: <HomePage /> },
    { path: 'projects', element: <ProjectsPage /> },
    ...STAGES.map(stage => ({ path: `councils/:id/${stagePath(stage)}`, element: <CouncilPage stage={stage} /> })),
  ],
}])

createRoot(document.getElementById('root')!).render(<React.StrictMode><RouterProvider router={router} /></React.StrictMode>)
