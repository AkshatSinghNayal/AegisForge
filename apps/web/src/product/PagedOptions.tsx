import { Button } from '@/ui';
export function MoreOptions({
  label,
  options,
}: {
  label: string;
  options: {
    data: unknown[] | undefined;
    error: string;
    loading: boolean;
    more: boolean;
    loadMore: () => void;
    retry: () => void;
  };
}) {
  return (
    <>
      {options.loading && <p role="status">Loading {label}…</p>}
      {options.error && (
        <div role="alert">
          {options.error}{' '}
          <Button type="button" onClick={options.retry}>
            Retry {label}
          </Button>
        </div>
      )}
      {options.more && (
        <div>
          <p>
            {options.data?.length} {label} loaded. More records may be
            available.
          </p>
          <Button
            type="button"
            variant="secondary"
            disabled={options.loading || !!options.error}
            onClick={options.loadMore}
          >
            Load more {label}
          </Button>
        </div>
      )}
    </>
  );
}
