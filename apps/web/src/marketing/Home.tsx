import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { Cockpit, CTA, FinalCTA, Metadata } from './Shared';
import { steps } from './content';
gsap.registerPlugin(ScrollTrigger);
export default function Home() {
  const root = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = root.current!;
    const media = gsap.matchMedia();
    media.add('(prefers-reduced-motion: no-preference)', () => {
      gsap.from(el.querySelectorAll('.hero-reveal'), {
        y: 20,
        opacity: 0,
        duration: 0.55,
        stagger: 0.1,
      });
      gsap.from(el.querySelector('.hero-cockpit'), {
        scale: 0.97,
        opacity: 0,
        duration: 0.65,
      });
      el.querySelectorAll('.m-reveal').forEach((group) =>
        gsap.from(group.children, {
          y: 18,
          opacity: 0,
          duration: 0.5,
          stagger: 0.08,
          scrollTrigger: { trigger: group, start: 'top 90%' },
        }),
      );
    });
    media.add(
      '(max-width: 1023px) and (prefers-reduced-motion: no-preference)',
      () => {
        el.querySelectorAll('.story-stage').forEach((stage) => {
          gsap.from(stage.children, {
            y: 16,
            opacity: 0,
            duration: 0.5,
            stagger: 0.08,
            scrollTrigger: { trigger: stage, start: 'top 90%' },
          });
        });
      },
    );
    media.add(
      '(min-width: 1024px) and (min-height: 760px) and (prefers-reduced-motion: no-preference)',
      () => {
        const section = el.querySelector('.m-story')!;
        const panels = gsap.utils.toArray<HTMLElement>('.story-stage', section);
        gsap.set(section, { height: 'auto' });
        gsap.set(panels, { position: 'absolute', inset: 0 });
        gsap.set(panels.slice(1), { autoAlpha: 0, y: 24 });
        const timeline = gsap.timeline({
          scrollTrigger: {
            trigger: section,
            start: 'top 90px',
            end: () => `+=${window.innerHeight * 3.2}`,
            pin: true,
            scrub: 0.8,
            invalidateOnRefresh: true,
          },
        });
        panels.forEach((panel, i) => {
          if (i)
            timeline
              .to(panels[i - 1]!, { autoAlpha: 0, y: -24, duration: 0.22 }, i)
              .to(panel, { autoAlpha: 1, y: 0, duration: 0.22 }, i);
        });
        timeline.to({}, { duration: 0.8 });
        gsap.to(el.querySelector('.story-progress'), {
          scaleX: 1,
          ease: 'none',
          scrollTrigger: {
            trigger: section,
            start: 'top 90px',
            end: () => `+=${window.innerHeight * 3.2}`,
            scrub: 0.8,
          },
        });
      },
    );
    return () => media.revert();
  }, []);
  return (
    <main id="main" ref={root}>
      <Metadata
        title="Scan. Understand. Enforce."
        description="Developer-first vulnerability intelligence. Explore evidence-preserving ZAP scanning, advisory AI and deterministic policy in AegisForge."
      />
      <section className="m-hero m-container">
        <p className="eyebrow hero-reveal">
          Developer-first vulnerability intelligence.
        </p>
        <h1 className="hero-reveal">
          Scan with intent.
          <br />
          Understand. <em>Enforce.</em>
        </h1>
        <p className="m-lead hero-reveal">
          Turn application security signals into a reviewable path forward.
          <br className="m-desktop" /> Evidence at the core. Developers in
          control.
        </p>
        <div className="hero-reveal">
          <CTA />
        </div>
        <div className="technical-panel hero-cockpit">
          <div className="panel-caption">
            <span>AEGISFORGE / PRODUCT BLUEPRINT</span>
            <span>01 — THE REVIEW WORKSPACE</span>
          </div>
          <Cockpit />
        </div>
      </section>
      <section className="m-trust m-container">
        <span>
          Built around trust,
          <br />
          <strong>not a black box.</strong>
        </span>
        <p>↳ Preserve the evidence</p>
        <p>↳ Keep AI advisory</p>
        <p>↳ Let policy decide</p>
      </section>
      <section className="m-container m-section">
        <p className="eyebrow">LESS FRICTION. MORE CONTEXT.</p>
        <div className="m-two m-reveal">
          <article className="outcome mint">
            <span className="outcome-icon" aria-hidden="true">
              ↗
            </span>
            <h2>
              Shorten security
              <br />
              feedback.
            </h2>
            <p>
              Bring discovery, observations and next steps into one review
              workflow. Spend less time reconstructing the story.
            </p>
            <Link to="/features/ci-cd">Explore the release workflow →</Link>
          </article>
          <article className="outcome cyan">
            <span className="outcome-icon" aria-hidden="true">
              ≋
            </span>
            <h2>
              Keep evidence
              <br />
              reviewable.
            </h2>
            <p>
              Trace guidance and decisions to their sources. Preserve the
              distinction between what was observed and what was inferred.
            </p>
            <Link to="/features/reports">Explore the evidence trail →</Link>
          </article>
        </div>
      </section>
      <section className="m-story m-container">
        <div className="story-heading">
          <p className="eyebrow">ONE WORKFLOW. FOUR CLEAR STEPS.</p>
          <h2>
            Keep the signal.
            <br />
            Move the work forward.
          </h2>
          <div className="story-track" aria-hidden="true">
            <div className="story-progress" />
          </div>
        </div>
        <ol className="sr-only" aria-label="Complete workflow">
          {steps.map((step) => (
            <li key={step.title}>
              <h3>{step.title}</h3>
              <p>
                {step.headline} {step.text}
              </p>
              <ul>
                {step.rows.map((row) => (
                  <li key={row}>{row}</li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
        <div className="story-deck" aria-hidden="true">
          {steps.map((s, i) => (
            <article className="story-stage" key={s.title}>
              <div className="story-copy">
                <p className="step-number">
                  0{i + 1} / 04 — {s.title}
                </p>
                <h3>{s.headline}</h3>
                <p>{s.text}</p>
                <ul>
                  {s.rows.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
              <div className={`story-visual tone-${i}`}>
                <Cockpit step={i} />
              </div>
            </article>
          ))}
        </div>
      </section>
      <section className="m-container m-section">
        <p className="eyebrow">THE WHOLE REVIEW, IN REACH</p>
        <h2>
          A workspace for the questions
          <br />
          that follow a scan.
        </h2>
        <div className="m-grid m-reveal">
          {[
            [
              'Findings',
              'Follow observations, evidence and review context.',
              'web-scanning',
            ],
            [
              'Scan history',
              'Understand coverage and incomplete runs.',
              'web-scanning',
            ],
            [
              'Policies',
              'Keep rules versioned and decisions deterministic.',
              'ci-cd',
            ],
            ['Reports', 'Share a redacted, reviewable trail.', 'reports'],
            [
              'API access',
              'Bring the workflow into your own tooling.',
              'api-scanning',
            ],
          ].map(([title, text, slug], i) => (
            <Link className="capability" to={`/features/${slug}`} key={title}>
              <span className="eyebrow">0{i + 1} ↗</span>
              <h3>{title}</h3>
              <p>{text}</p>
            </Link>
          ))}
        </div>
      </section>
      <section className="m-container m-section">
        <div className="m-section-heading">
          <div>
            <p className="eyebrow">MEET YOUR WORKFLOW</p>
            <h2>Built to connect.</h2>
          </div>
          <p>
            Integration roadmap.
            <br />
            Connections are not live in this release.
          </p>
        </div>
        <div className="integration-grid">
          {[
            ['GitHub Actions', 'Release checks'],
            ['Slack', 'Team notifications'],
            ['Email', 'Review updates'],
            ['Webhooks', 'Your workflows'],
            ['S3', 'Private artifacts'],
            ['Gemini', 'Advisory analysis'],
            ['ZAP', 'Scanner observations'],
          ].map(([title, text]) => (
            <Link to="/docs/integrations" key={title}>
              <strong>{title} ↗</strong>
              <span>{text}</span>
            </Link>
          ))}
        </div>
      </section>
      <section className="m-boundary m-container">
        <p className="eyebrow">BOUNDARIES ARE PART OF THE PRODUCT</p>
        <h2>
          Permission first.
          <br />
          Evidence protected.
          <br />
          <em>Human judgment intact.</em>
        </h2>
        <p>
          The architecture requires current authorization for every scan,
          redacted evidence for everyday review and explicit limits on AI. These
          controls are implementation requirements, not a claim of
          certification.
        </p>
        <Link className="button secondary" to="/security">
          Read our security boundaries →
        </Link>
      </section>
      <FinalCTA />
    </main>
  );
}
