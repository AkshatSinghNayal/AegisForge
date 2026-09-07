import { z } from 'zod';
export const organization = z.object({
  id: z.string().uuid(),
  name: z.string(),
  role: z.enum(['owner', 'admin', 'developer', 'viewer']),
});
export const meSchema = z.object({
  id: z.string().uuid(),
  email: z.string(),
  display_name: z.string(),
  email_verified: z.boolean(),
  organizations: z.array(organization),
});
export type Me = z.infer<typeof meSchema>;
const credential = z.object({
  access_token: z.string(),
  expires_in: z.number(),
  token_type: z.literal('Bearer'),
});
let access: string | null = null;
let csrf: string | null = null;
let refreshing: Promise<boolean> | null = null;
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
async function csrfToken() {
  if (!csrf) {
    const response = await fetch('/api/v1/auth/csrf', {
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error('Unable to establish a secure session.');
    csrf = z
      .object({ csrf_token: z.string() })
      .parse(await response.json()).csrf_token;
  }
  return csrf;
}
export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  method = 'GET',
  body?: unknown,
  retry = true,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (access) headers.Authorization = `Bearer ${access}`;
  if (method !== 'GET') headers['X-CSRF-Token'] = await csrfToken();
  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (
    response.status === 401 &&
    retry &&
    ![
      '/auth/refresh',
      '/auth/sign-in',
      '/auth/register',
      '/auth/forgot-password',
      '/auth/reset-password',
      '/auth/verify-email',
    ].includes(path)
  ) {
    if (await bootstrap()) return request(path, schema, method, body, false);
  }
  if (!response.ok) {
    const parsed = z
      .object({ error: z.object({ message: z.string() }) })
      .safeParse(await response.json());
    throw new ApiError(
      response.status,
      parsed.success
        ? parsed.data.error.message
        : 'Request could not be completed.',
    );
  }
  return schema.parse(await response.json());
}
export function bootstrap(): Promise<boolean> {
  const refresh = () =>
    request('/auth/refresh', credential, 'POST', undefined, false)
      .then((result) => {
        access = result.access_token;
        return true;
      })
      .catch((error: unknown) => {
        access = null;
        if (error instanceof ApiError && error.status === 401) return false;
        throw error;
      });
  refreshing ??= (
    navigator.locks
      ? navigator.locks.request('aegis-refresh', refresh)
      : refresh()
  ).finally(() => {
    refreshing = null;
  });
  return refreshing;
}
export async function login(email: string, password: string) {
  access = (
    await request(
      '/auth/sign-in',
      credential,
      'POST',
      { email, password },
      false,
    )
  ).access_token;
}
export const messageSchema = z.object({ message: z.string() });
export async function logout(all = false) {
  await request(
    all ? '/auth/revoke-all' : '/auth/sign-out',
    messageSchema,
    'POST',
  );
  access = null;
}
