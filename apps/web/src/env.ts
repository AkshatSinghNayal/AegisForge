import { z } from 'zod';
export const envSchema = z.object({
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
