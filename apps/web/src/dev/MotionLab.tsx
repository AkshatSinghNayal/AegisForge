import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { Card, LinkButton, PageHeader, TerminalPanel } from '@/ui';
import { PublicLayout } from '@/ui/shells';
gsap.registerPlugin(ScrollTrigger);
const transcript =
  '$ forge motion --simulate\n\n✓ Authorization example loaded\n✓ Observation example assembled\n✓ Review example ready\n\nSimulation only. No scan executed.';
export default function MotionLab() {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = root.current!;
    let alive = true;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      gsap.from(el.querySelectorAll('.reveal'), {
        y: 28,
        opacity: 0,
        duration: 0.7,
        stagger: 0.12,
      });
      el.querySelectorAll('.stagger-group').forEach((group) => {
        gsap.from(group.children, {
          y: 32,
          opacity: 0,
          stagger: 0.15,
          duration: 0.65,
          scrollTrigger: { trigger: group, start: 'top 85%' },
        });
      });
      const metric = el.querySelector<HTMLElement>('[data-count]')!;
      const value = { n: 0 };
      gsap.to(value, {
        n: 128,
        duration: 1.5,
        roundProps: 'n',
        scrollTrigger: { trigger: metric, start: 'top 90%' },
        onUpdate: () => {
          metric.textContent = String(value.n);
        },
      });
      const terminal = el.querySelector<HTMLElement>('[data-terminal]')!;
      const chars = { n: 0 };
      gsap.to(chars, {
        n: transcript.length,
        duration: 3,
        ease: 'none',
        roundProps: 'n',
        scrollTrigger: { trigger: terminal, start: 'top 90%' },
        onUpdate: () => {
          terminal.textContent = transcript.slice(0, chars.n);
        },
      });
      gsap.to(el.querySelector('.reading-progress'), {
        scaleX: 1,
        ease: 'none',
        scrollTrigger: {
          trigger: el,
          start: 'top top',
          end: 'bottom bottom',
          scrub: true,
        },
      });
      gsap.to(el.querySelector('.motion-grid'), {
        y: 70,
        ease: 'none',
        scrollTrigger: {
          trigger: el,
          start: 'top top',
          end: 'bottom top',
          scrub: true,
        },
      });
      const panels = el.querySelectorAll('.story-panel');
      gsap.set(panels[1]!, { opacity: 0 });
      gsap
        .timeline({
          scrollTrigger: {
            trigger: el.querySelector('.pinned-story'),
            start: 'top 100px',
            end: '+=650',
            pin: true,
            scrub: 0.4,
            invalidateOnRefresh: true,
          },
        })
        .to(panels[0]!, { opacity: 0 })
        .to(panels[1]!, { opacity: 1 }, 0);
      return () => {
        metric.textContent = '128';
        terminal.textContent = transcript;
      };
    });
    const refresh = () => {
      if (alive) ScrollTrigger.refresh();
    };
    void document.fonts.ready.then(refresh);
    const images = Array.from(el.querySelectorAll('img'));
    images.forEach((img) => img.addEventListener('load', refresh));
    window.addEventListener('load', refresh);
    return () => {
      alive = false;
      images.forEach((img) => img.removeEventListener('load', refresh));
      window.removeEventListener('load', refresh);
      media.revert();
    };
  }, []);
  return (
    <PublicLayout>
      <main ref={root} id="main" className="motion-main">
        <div className="reading-progress" aria-hidden="true" />
        <div className="motion-grid" aria-hidden="true" />
        <div className="motion-container">
          <div className="reveal">
            <PageHeader
              eyebrow="EXPERIMENT 002 / MOTION LABORATORY"
              title="Clarity in motion."
              description="A little movement. A stronger sense of direction. Scroll to explore how AegisForge reveals, connects, and explains."
              action={<LinkButton to="/dev/ui">UI library ↗</LinkButton>}
            />
          </div>
          <div className="motion-intro reveal">
            <span className="badge">LOCAL SIMULATION</span>
            <p>
              Built to guide attention.
              <br />
              <span className="muted">Designed to respect yours.</span>
            </p>
            <a href="#experiments" className="button ghost">
              Explore experiments ↓
            </a>
          </div>
          <section id="experiments">
            <div className="section-heading">
              <h2>01 / Rhythm & reveal</h2>
              <span className="muted">Opacity + transform</span>
            </div>
            <div className="three-col stagger-group">
              {[
                'Establish context',
                'Reveal evidence',
                'Support a decision',
              ].map((title, i) => (
                <Card key={title}>
                  <p className="eyebrow">0{i + 1}</p>
                  <h3>{title}</h3>
                  <p>
                    Staggered entry gives each piece of information a moment to
                    land.
                  </p>
                </Card>
              ))}
            </div>
          </section>
          <section className="two-col motion-section">
            <Card>
              <p className="eyebrow">02 / COUNT-UP METRIC</p>
              <div className="metric" aria-hidden="true" data-count>
                128
              </div>
              <span className="sr-only">128 illustrative components</span>
              <p>Illustrative count · no measured product results</p>
            </Card>
            <div>
              <p className="eyebrow">03 / TERMINAL SIMULATION</p>
              <TerminalPanel>
                <span aria-hidden="true" data-terminal>
                  {transcript}
                </span>
                <span className="sr-only">{transcript}</span>
              </TerminalPanel>
            </div>
          </section>
          <section className="pinned-story">
            <div>
              <p className="eyebrow">04 / PIN + CROSSFADE</p>
              <h2>
                From observation
                <br />
                to understanding.
              </h2>
              <p>
                One steady frame. Two perspectives.
                <br />
                Scroll to transition between mock panels.
              </p>
              <span className="badge">Illustrative content</span>
            </div>
            <div className="story-panels">
              <Card className="story-panel">
                <p className="eyebrow">01 / OBSERVATION</p>
                <h3>Keep the source in sight.</h3>
                <div className="evidence-lines" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </div>
                <p>Mock evidence panel. No findings or scan results.</p>
              </Card>
              <Card className="story-panel">
                <p className="eyebrow">02 / EXPLANATION</p>
                <h3>Make the next step clear.</h3>
                <p>
                  Mock guidance panel. Explanations remain advisory and separate
                  from evidence.
                </p>
                <span className="badge">UI demonstration</span>
              </Card>
            </div>
          </section>
          <section className="motion-outro">
            <p className="eyebrow">05 / ACCESSIBLE BY DESIGN</p>
            <h2>Stillness is a first-class state.</h2>
            <p>
              Prefer reduced motion? Every experiment becomes static content in
              normal document flow, with no pinning or scrubbing.
            </p>
            <LinkButton to="/dev/ui">
              Back to the component library ↗
            </LinkButton>
          </section>
        </div>
      </main>
    </PublicLayout>
  );
}
