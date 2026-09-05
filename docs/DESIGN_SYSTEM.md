# AegisForge design system v0.2

Phase 2 is a frontend laboratory, not an operational product. Run `pnpm --filter @aegisforge/web dev` and visit `/dev/ui` and `/dev/motion`. Both modules are lazy imported behind Vite's compile-time `import.meta.env.DEV`; production builds omit the lab modules and render Page not found at both URLs. The existing `/` health utility remains functional. No new environment variables, backend features, authorization claims or domain data are introduced.

## Identity and foundations

`apps/web/src/ui/index.tsx` exports the original `Wordmark`: live AegisForge text plus a hand-authored shield enclosing an anvil. The mark is decorative beside its visible name. Give a link around it a meaningful accessible name. Do not use it as a scanner success indicator. No third-party brand assets or compositions are used. No reference screenshots/video were present in the supplied workspace for direct comparison.

`apps/web/src/style.css` defines the dark default theme. Semantic custom properties are the theme boundary; a future `[data-theme="light"]` can override roles without changing component APIs. Light mode is not implemented or verified. System sans avoids external font requests and font-swap layout shifts; Inter is used only if locally available. Monospace presents metadata and evidence. Font loading still triggers ScrollTrigger refresh for future font additions.

| Token family | Values / usage                                                                                                                                                                                                                  |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Color        | Canvas `#0b1012`, surface `#141c20`, raised `#1c272c`, text `#eef3ef`, muted `#a4b3b9`, interactive border `#60757d`, decorative separator `#29383e`, accent `#a3f0c2`, accent ink `#10281b`, ember `#ffb080`, danger `#ff9caa` |
| Typography   | `--font-sans`, `--font-mono`; xs 12, sm 14, base 16, lg 20, xl 24px; fluid headings via clamp                                                                                                                                   |
| Spacing      | `--space-1/2/3/4/6/8/12/16`: 4, 8, 12, 16, 24, 32, 48, 64px                                                                                                                                                                     |
| Radius       | sm 6, md 12, lg 20px                                                                                                                                                                                                            |
| Shadow       | `--shadow-overlay`: 0 20px 80px translucent black                                                                                                                                                                               |
| Layers       | header 20, menu 30, toast 50; native dialog/popover use the browser top layer                                                                                                                                                   |
| Motion       | fast 140ms, normal 240ms, reveal 700ms; `--ease-out`; animate opacity/transforms, never layout dimensions                                                                                                                       |

Use muted text on canvas/surface/raised surfaces, mint with accent ink for primary controls, and explicit text for severity/status. Decorative separators do not identify interactive controls. Interactive borders and focus rings use higher contrast roles. Disabled controls are visually distinct and excluded from interaction. Native input labels, links, buttons, summaries, menu items and tabs have at least 44px tall targets; checkbox/radio labels provide the expanded click target.

## Component usage

Import primitives from `@/ui`, layouts from `@/ui/shells`. Examples are executable in `src/dev/UiLab.tsx`.

| Component                         | Contract                                                                                                                                                                                                      |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Button                            | Native button props; `variant`: primary, secondary, ghost, danger; default type button; disabled uses native behavior                                                                                         |
| IconButton                        | Button props plus required `label`; children are a decorative icon                                                                                                                                            |
| LinkButton                        | `to`, `children`; router navigation styled as an action                                                                                                                                                       |
| Input                             | Native input props plus required `label`, optional `error`; unique IDs and linked error description                                                                                                           |
| Textarea / Select                 | Native props plus required `label`; pass option children to Select                                                                                                                                            |
| Checkbox                          | Native input props plus `label`; controlled or uncontrolled                                                                                                                                                   |
| RadioGroup                        | `label`, unique `name`, string `options`; native exclusive selection and keyboard behavior                                                                                                                    |
| Tabs                              | `items: {label, content}[]`; roving focus with Left/Right/Home/End; linked panels; labels must be unique                                                                                                      |
| Tooltip                           | `label` for explanation, `children` for trigger; hover/focus, Escape dismissal; use for supplemental text only                                                                                                |
| Popover                           | `label`, `children`; native auto popover, Escape/outside dismissal; for supporting content, not required form steps                                                                                           |
| Dialog / Drawer                   | Controlled `open`, `onClose`, `title`, `children`; native modal/inert background, scroll lock, focus wrapping/restoration, Escape and backdrop dismissal                                                      |
| Dropdown                          | `label`, `items: {label, onSelect}[]`; arrows/Home/End, Enter/Space selection, Escape, outside dismissal and focus return                                                                                     |
| Toast                             | `message`, `onClose`; persistent until explicit dismiss so announcements are not time-limited                                                                                                                 |
| Badge / Card                      | `children`; Card accepts additive `className`                                                                                                                                                                 |
| DataTable                         | `caption`, `columns: string[]`, `rows: ReactNode[][]`; semantic headers/caption and focusable overflow region; provide matching cell counts; sorting/pagination/selection are deliberately outside this shell |
| Skeleton                          | Optional `label`; stable 120px loading region, no perpetual animation                                                                                                                                         |
| EmptyState                        | `title`, `children`; supply useful explanation and action                                                                                                                                                     |
| ErrorState                        | `message`, `onRetry`; explicit error announcement and working retry callback                                                                                                                                  |
| StatusDot                         | Required `label`; dot never conveys meaning alone                                                                                                                                                             |
| SeverityBadge                     | `severity`: critical, high, medium, low, info; text plus color, never a policy evaluation                                                                                                                     |
| CodeBlock / CopyButton            | `code` / `text`; text is escaped by React; clipboard failure is visible; use redacted content only                                                                                                            |
| TerminalPanel                     | `children`; monospace, wrapping output; this lab labels output as local simulation                                                                                                                            |
| Stepper                           | `steps`, zero-based `current`; noninteractive ordered progression with `aria-current="step"`                                                                                                                  |
| Accordion                         | `items: {title, content}[]`; native details/summary allows multiple disclosures                                                                                                                               |
| PageHeader                        | `eyebrow`, `title`, `description`, optional `action`; one h1 per page                                                                                                                                         |
| MarketingHeader / MarketingFooter | Responsive wordmark, real lab/health navigation, mobile modal navigation                                                                                                                                      |
| AppSidebar / AppTopbar / AppShell | Shell specimens, not authentication boundaries; sidebar becomes a drawer below 1024px; closes on navigation or desktop resize                                                                                 |
| PublicLayout                      | Public shell and scoped Lenis lifecycle; never wrap authenticated app content in this layout                                                                                                                  |

```tsx
const [open, setOpen] = useState(false);
<Button onClick={() => setOpen(true)}>Review details</Button>
<Dialog open={open} onClose={() => setOpen(false)} title="Review details">
  <p>Evidence-linked context goes here.</p>
  <Button onClick={() => setOpen(false)}>Done</Button>
</Dialog>
```

Callers own validation, data loading, permissions and business behavior. No component establishes scan authorization, policy status or tenant trust. Future application shells should receive their own route catalog when those routes are actually implemented; current links point only to working lab/health routes. Do not expose development catalog links in production product layouts.

## Motion contract

`src/dev/MotionLab.tsx` contains fade-up and staggered reveals, an illustrative count of 128, terminal typing, a pinned/crossfading mock story, transform-based reading progress and subtle grid parallax. No mock finding is represented as real evidence. GSAP ScrollTrigger is used only for this public scrollytelling experiment. Lenis exists only while PublicLayout is mounted, and native scrolling works without it.

`gsap.matchMedia` owns the animation lifecycle. Reduced motion removes animation, pin spacers and scrubbing; both panels render sequentially with complete metric/terminal content. Changing the preference at runtime reverts animations. Cleanup reverts GSAP context and destroys Lenis on navigation. Font readiness, window load and image load trigger guarded refreshes; listeners are removed on unmount. Fixed terminal space, tabular metric digits, grid-overlaid normal-motion panels, system fonts and transform/opacity animation prevent animation-induced reflow. The reading progress is decorative, not an ARIA live stream.

## Verification and maintenance

- `pnpm --filter @aegisforge/web test`: component interaction tests plus existing foundation tests.
- `pnpm --filter @aegisforge/web exec playwright test`: production health/exclusion checks and development labs; starts separate production preview and dev servers.
- Committed Chromium/Linux screenshot baselines at 390 and 1440px use reduced motion for stable, complete-page comparison. Update intentionally with `--update-snapshots` and inspect the images before accepting them.
- Overflow assertions cover 360, 390, 768, 1024, 1280, 1440 and 1920px. Axe checks both labs at mobile/desktop. A separate normal-motion test exercises pinning, count-up, live reduced-motion changes and cleanup. Modal browser tests cover focus wrapping, Escape and navigation drawer behavior.
- Automated smoke tests are not exhaustive WCAG certification. Native dialog/popover support requires modern browsers; Chromium is the verified browser. Screen-reader and additional-browser review remain future regression work.
