import { lazy } from 'react';
import { Route, Routes } from 'react-router-dom';
import { App } from '@/App';
const UiLab = import.meta.env.DEV ? lazy(() => import('@/dev/UiLab')) : null;
const MotionLab = import.meta.env.DEV
  ? lazy(() => import('@/dev/MotionLab'))
  : null;
const MarketingLayout = lazy(() => import('@/marketing/Shared'));
const Home = lazy(() => import('@/marketing/Home'));
const Pages = lazy(() => import('@/marketing/Pages'));
const Docs = lazy(() => import('@/marketing/Docs'));
const Legal = lazy(() => import('@/marketing/Legal'));
export function RootRoutes() {
  return (
    <Routes>
      <Route path="/status" element={<App />} />
      <Route element={<MarketingLayout />}>
        <Route path="/" element={<Home />} />
        {[
          '/platform',
          '/pricing',
          '/features/web-scanning',
          '/features/api-scanning',
          '/features/ai-analysis',
          '/features/ci-cd',
          '/features/reports',
        ].map((path) => (
          <Route key={path} path={path} element={<Pages />} />
        ))}
        <Route path="/docs" element={<Docs />} />
        <Route path="/docs/:slug" element={<Docs />} />
        {['security', 'privacy', 'terms'].map((slug) => (
          <Route key={slug} path={`/${slug}`} element={<Legal />} />
        ))}
      </Route>
      {UiLab && <Route path="/dev/ui" element={<UiLab />} />}
      {MotionLab && <Route path="/dev/motion" element={<MotionLab />} />}
      <Route
        path="*"
        element={
          <main className="lab-main">
            <h1>Page not found</h1>
            <a className="button secondary" href="/">
              AegisForge home
            </a>
          </main>
        }
      />
    </Routes>
  );
}
