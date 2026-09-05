import { useQuery } from '@tanstack/react-query';
import { z } from 'zod';
import { env } from '@/env';
const readiness = z.object({ status: z.enum(['ready', 'unavailable']) });
export function App() {
  const health = useQuery({
    queryKey: ['readiness'],
    queryFn: async () => {
      const response = await fetch(`${env.VITE_API_BASE_URL}/health/ready`, {
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error('Service unavailable');
      return readiness.parse(await response.json());
    },
    retry: false,
    refetchInterval: 15000,
  });
  return (
    <main className="mx-auto max-w-2xl px-6 py-20">
      <p className="text-teal-300">AegisForge · Local foundation</p>
      <h1 className="mt-4 text-4xl font-semibold">Service health</h1>
      <p className="mt-6" role="status">
        {health.isPending
          ? 'Checking dependencies…'
          : health.isError
            ? 'API or dependencies unavailable.'
            : health.data.status === 'ready'
              ? 'API, PostgreSQL and Redis are ready.'
              : 'Dependencies unavailable.'}
      </p>
      <button
        className="mt-6 rounded border border-teal-300 px-4 py-2 focus-visible:outline-2 focus-visible:outline-offset-4 disabled:opacity-50"
        onClick={() => void health.refetch()}
        disabled={health.isFetching}
      >
        Refresh status
      </button>
      <p className="mt-8 text-slate-300">
        Phase 1 foundation. Scanning and account features are not implemented.
      </p>
    </main>
  );
}
