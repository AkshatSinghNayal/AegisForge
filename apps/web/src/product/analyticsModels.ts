import { z } from 'zod';
const metric = z.object({
  label: z.string(),
  value: z.number().nullable(),
  unit: z.string(),
});
export const series = z.array(
  z.object({ label: z.string(), value: z.number() }),
);
export const dashboardSchema = z.object({
  generated_at: z.string(),
  date_from: z.string(),
  date_to: z.string(),
  timezone: z.string(),
  excluded_scans: z.number(),
  metrics: z.array(metric),
  severity: series,
  categories: series,
  owasp: series,
  exclusions: z.array(metric),
  lifecycle: series,
  duration: series,
  completion: series,
  risk_total: z.number(),
  risk: z.array(
    z.object({
      project_id: z.string(),
      target_id: z.string(),
      project: z.string(),
      target: z.string(),
      open_findings: z.number(),
      high_critical: z.number(),
    }),
  ),
  activity: z.array(
    z.object({
      id: z.string(),
      target_id: z.string(),
      state: z.string(),
      completeness: z.string(),
      created_at: z.string(),
    }),
  ),
  actions: z.array(metric),
  action_items: z.array(
    z.object({ label: z.string(), path: z.string().startsWith('/app/') }),
  ),
});
export const optionsSchema = z.array(
  z.object({ id: z.string(), project_id: z.string(), label: z.string() }),
);
export function csvCell(value: string | number) {
  const text = String(value);
  return `"${(/^[=+@\-\t\r\n]/.test(text.trimStart()) ? "'" : '') + text.replaceAll('"', '""')}"`;
}
export function exportCSV(headers: string[], rows: (string | number)[][]) {
  const blob = new Blob(
    [[headers, ...rows].map((row) => row.map(csvCell).join(',')).join('\r\n')],
    { type: 'text/csv;charset=utf-8' },
  );
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'aegisforge-table.csv';
  a.click();
  URL.revokeObjectURL(url);
}
