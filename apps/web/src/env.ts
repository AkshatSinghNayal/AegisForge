import { z } from 'zod';
export const envSchema = z.object({
  VITE_SITE_URL: z
    .url()
    .refine((value) => {
      const url = new URL(value);
      return (
        ['http:', 'https:'].includes(url.protocol) &&
        !url.username &&
        !url.password &&
        url.pathname === '/' &&
        !url.search &&
        !url.hash
      );
    }, 'Expected an HTTP(S) origin')
    .default('http://localhost:5173'),
  VITE_SECURITY_CONTACT: z.union([z.literal(''), z.email()]).default(''),
  VITE_API_BASE_URL: z
    .union([
      z.literal(''),
      z
        .url()
        .refine((url) => ['http:', 'https:'].includes(new URL(url).protocol)),
    ])
    .default(''),
});
export const env = envSchema.parse(import.meta.env);
