import React, { lazy, Suspense } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from '@/App';
import './style.css';
const UiLab = import.meta.env.DEV ? lazy(() => import('@/dev/UiLab')) : null;
const MotionLab = import.meta.env.DEV
  ? lazy(() => import('@/dev/MotionLab'))
  : null;
const client = new QueryClient();
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <Suspense fallback={<p role="status">Loading laboratory…</p>}>
          <Routes>
            <Route path="/" element={<App />} />
            {UiLab && <Route path="/dev/ui" element={<UiLab />} />}
            {MotionLab && <Route path="/dev/motion" element={<MotionLab />} />}
            <Route
              path="*"
              element={
                <main className="lab-main">
                  <h1>Page not found</h1>
                  <a className="button secondary" href="/">
                    Service health
                  </a>
                </main>
              }
            />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
