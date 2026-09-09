import { z } from 'zod';
export const eventSchema = z.object({
  sequence: z.number().int().positive(),
  stage: z.string(),
  message_code: z.string(),
  attempt: z.number().int().positive(),
  created_at: z.string(),
});
export type Event = z.infer<typeof eventSchema>;
export function mergeEvents(previous: Event[], incoming: Event): Event[] {
  if (previous.some((event) => event.sequence === incoming.sequence))
    return previous;
  return [...previous, incoming].sort((a, b) => a.sequence - b.sequence);
}
