import { useEffect, useState } from 'react';
import { z } from 'zod';
import { request } from './client';

const pageSize = 200;
export function usePagedOptions<T extends { id: string }>(
  path: string,
  schema: z.ZodType<T[]>,
) {
  const [cursor, setCursor] = useState({ path, offset: 0 });
  const offset = cursor.path === path ? cursor.offset : 0;
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<{
    path: string;
    offset: number;
    rows: T[];
    more: boolean;
  }>();
  const [failure, setFailure] = useState<{
    path: string;
    offset: number;
    message: string;
  }>();
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active)
        setCursor((previous) =>
          previous.path === path ? previous : { path, offset: 0 },
        );
    });
    const url = offset
      ? `${path}${path.includes('?') ? '&' : '?'}offset=${offset}`
      : path;
    void request(url, schema)
      .then((rows) => {
        if (!active) return;
        setResult((previous) => ({
          path,
          offset,
          more: rows.length === pageSize,
          rows: [
            ...new Map(
              [
                ...(offset && previous?.path === path ? previous.rows : []),
                ...rows,
              ].map((row) => [row.id, row]),
            ).values(),
          ],
        }));
        setFailure(undefined);
      })
      .catch((error: unknown) => {
        if (active)
          setFailure({
            path,
            offset,
            message:
              error instanceof Error ? error.message : 'Options unavailable.',
          });
      });
    return () => {
      active = false;
    };
  }, [path, offset, schema, revision]);
  const current = result?.path === path ? result : undefined;
  const error =
    failure?.path === path && failure.offset === offset ? failure.message : '';
  return {
    data: current?.rows,
    error,
    loading: !error && (!current || current.offset !== offset),
    more: current?.more ?? false,
    loadMore: () =>
      setCursor({ path, offset: (current?.offset ?? 0) + pageSize }),
    refresh: () => {
      setCursor({ path, offset: 0 });
      setResult(undefined);
      setFailure(undefined);
      setRevision((v) => v + 1);
    },
    retry: () => {
      setFailure(undefined);
      setRevision((v) => v + 1);
    },
  };
}
