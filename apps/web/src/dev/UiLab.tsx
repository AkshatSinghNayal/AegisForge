import { useState } from 'react';
import { ArrowUpRight, Plus, ShieldCheck } from 'lucide-react';
import {
  Accordion,
  Badge,
  Button,
  Card,
  Checkbox,
  CodeBlock,
  DataTable,
  Dialog,
  Drawer,
  Dropdown,
  EmptyState,
  ErrorState,
  IconButton,
  Input,
  LinkButton,
  PageHeader,
  Popover,
  RadioGroup,
  Select,
  SeverityBadge,
  Skeleton,
  StatusDot,
  Stepper,
  Tabs,
  TerminalPanel,
  Textarea,
  Toast,
  Tooltip,
} from '@/ui';
import { AppShell } from '@/ui/shells';
export default function UiLab() {
  const [dialog, setDialog] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [toast, setToast] = useState('');
  const [retried, setRetried] = useState(false);
  return (
    <AppShell>
      <main id="main" className="lab-main">
        <PageHeader
          eyebrow="AEGISFORGE / DESIGN SYSTEM / V0.2"
          title="The forge, assembled."
          description="A shared language for clear decisions. Explore the foundations, components, and states behind AegisForge."
          action={
            <LinkButton to="/dev/motion">
              Motion lab <ArrowUpRight size={16} />
            </LinkButton>
          }
        />
        <div className="section-heading">
          <h2>01 / Foundations</h2>
          <Badge>Dark / default</Badge>
        </div>
        <div className="foundation-grid">
          <Card className="brand-card">
            <ShieldCheck size={30} />
            <h3>Precision meets resilience.</h3>
            <p>
              Quiet surfaces. Decisive signals.
              <br />
              Evidence always comes first.
            </p>
            <span className="eyebrow">ORIGINAL AEGISFORGE IDENTITY</span>
          </Card>
          <Card>
            <h3>Core spectrum</h3>
            <div className="swatches">
              {[
                ['Canvas', '#0b1012'],
                ['Surface', '#141c20'],
                ['Mint', '#a3f0c2'],
                ['Ember', '#ffb080'],
              ].map(([name, color]) => (
                <div key={name}>
                  <div style={{ background: color }} />
                  <strong>{name}</strong>
                  <code>{color}</code>
                </div>
              ))}
            </div>
            <p className="muted">Semantic roles, ready for future themes.</p>
          </Card>
          <Card>
            <p className="eyebrow">TYPOGRAPHY</p>
            <div className="type-specimen">
              Aa<span>Bb</span>
            </div>
            <p>System sans / editorial clarity</p>
            <code>MONOSPACE / EVIDENCE + METADATA</code>
          </Card>
        </div>
        <div className="section-heading">
          <h2>02 / Actions & inputs</h2>
          <span className="muted">44px minimum interaction</span>
        </div>
        <div className="two-col">
          <Card>
            <h3>Every action, intentional.</h3>
            <div className="row">
              <Button onClick={() => setDialog(true)}>
                <Plus size={16} />
                Open dialog
              </Button>
              <Button variant="secondary" onClick={() => setDrawer(true)}>
                Open drawer
              </Button>
              <IconButton
                label="Show notification"
                variant="ghost"
                onClick={() =>
                  setToast('This is a local component demonstration.')
                }
              >
                <ArrowUpRight size={20} />
              </IconButton>
              <Button disabled>Unavailable</Button>
            </div>
            <div className="row">
              <Dropdown
                label="Actions"
                items={[
                  {
                    label: 'Show notification',
                    onSelect: () =>
                      setToast('Action selected in the design lab.'),
                  },
                  { label: 'Open details', onSelect: () => setDialog(true) },
                ]}
              />
              <Popover label="About this lab">
                <h3>Development only</h3>
                <p>
                  These controls demonstrate UI behavior without contacting a
                  backend.
                </p>
              </Popover>
              <Tooltip label="No real scan is performed">
                Simulation info ⓘ
              </Tooltip>
            </div>
            <Input label="Project name" placeholder="e.g. Customer portal" />
            <Textarea
              label="Description"
              placeholder="Describe this local example"
              rows={3}
            />
          </Card>
          <Card>
            <h3>Selection & validation</h3>
            <Select label="Environment" defaultValue="local">
              <option value="local">Local simulation</option>
              <option value="staging">Staging example</option>
            </Select>
            <Input
              label="Example invalid URL"
              defaultValue="not-a-url"
              error="Enter a URL beginning with https://."
            />
            <Checkbox label="Include optional example metadata" />
            <RadioGroup
              name="mode"
              label="Display density"
              options={['Comfortable', 'Compact']}
            />
          </Card>
        </div>
        <div className="section-heading">
          <h2>03 / Evidence & feedback</h2>
          <Badge>Illustrative data only</Badge>
        </div>
        <Card>
          <Tabs
            items={[
              {
                label: 'Overview',
                content: (
                  <>
                    <div className="row">
                      <StatusDot label="Component ready" />
                      {(
                        ['critical', 'high', 'medium', 'low', 'info'] as const
                      ).map((s) => (
                        <SeverityBadge severity={s} key={s} />
                      ))}
                    </div>
                    <DataTable
                      caption="Illustrative component inventory — not scan results"
                      columns={['Component', 'Category', 'State']}
                      rows={[
                        ['Dialog', 'Overlay', <Badge key="a">Ready</Badge>],
                        [
                          'Data table',
                          'Evidence',
                          <Badge key="b">Shell</Badge>,
                        ],
                      ]}
                    />
                  </>
                ),
              },
              {
                label: 'Code example',
                content: (
                  <CodeBlock
                    code={
                      '<Button onClick={openDialog}>Review details</Button>'
                    }
                  />
                ),
              },
              { label: 'Loading', content: <Skeleton /> },
            ]}
          />
        </Card>
        <div className="two-col section-gap">
          <Card>
            <EmptyState title="A clean starting point">
              <p>No examples have been added to this local collection.</p>
              <Button
                variant="secondary"
                onClick={() => setToast('Example interaction complete.')}
              >
                Try an interaction
              </Button>
            </EmptyState>
          </Card>
          <Card>
            {retried ? (
              <>
                <StatusDot label="Retry interaction complete" />
                <p>This is UI feedback only.</p>
                <Button variant="secondary" onClick={() => setRetried(false)}>
                  Reset error example
                </Button>
              </>
            ) : (
              <ErrorState
                message="Example: evidence could not be loaded."
                onRetry={() => setRetried(true)}
              />
            )}
          </Card>
        </div>
        <div className="section-heading">
          <h2>04 / Structure & disclosure</h2>
        </div>
        <Stepper steps={['Authorize', 'Observe', 'Review']} current={1} />
        <div className="two-col section-gap">
          <Card>
            <Accordion
              items={[
                {
                  title: 'What does this laboratory do?',
                  content: (
                    <p>
                      It exercises reusable components. All examples are local
                      and illustrative.
                    </p>
                  ),
                },
                {
                  title: 'How is motion handled?',
                  content: (
                    <p>
                      Transforms and opacity preserve layout. Reduced motion
                      keeps content in normal flow.
                    </p>
                  ),
                },
              ]}
            />
          </Card>
          <TerminalPanel>
            {
              '$ forge design --local\n\n✓ Tokens loaded\n✓ Components assembled\n\nUI simulation only. No target contacted.'
            }
          </TerminalPanel>
        </div>
        <p className="lab-end">
          AEGISFORGE DESIGN SYSTEM <span>FORM FOLLOWS EVIDENCE.</span>
        </p>
        <Dialog
          open={dialog}
          onClose={() => setDialog(false)}
          title="Review the details"
        >
          <p>
            This modal is a local interaction example. Escape closes it and
            focus returns to the trigger.
          </p>
          <Button
            onClick={() => {
              setDialog(false);
              setToast('Review completed in the UI lab.');
            }}
          >
            Complete review
          </Button>
        </Dialog>
        <Drawer
          open={drawer}
          onClose={() => setDrawer(false)}
          title="Component details"
        >
          <p>Drawers hold supporting context without losing your place.</p>
          <Button onClick={() => setDrawer(false)}>Done</Button>
        </Drawer>
        {toast && <Toast message={toast} onClose={() => setToast('')} />}
      </main>
    </AppShell>
  );
}
