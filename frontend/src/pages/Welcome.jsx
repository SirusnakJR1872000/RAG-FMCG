// Public landing page (amendment A-05; style from docs/images/mockup_0_landing_style_only.png and
// docs/prototype). Only claims the system really meets: no "Request Demo", FMCG/GMA only as
// Roadmap (design brief §9.3 #13). Compliance wording is "designed to support", never "compliant".
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import Icon from '../components/Icon'
import { FictionalTag } from '../components/ui'
import { FICTIONAL_SOPS, PUBLIC_GUIDANCE } from '../landing/corpus'
import { landingFor } from '../lib/nav'

const SECTIONS = [['features', 'Features'], ['how', 'How it works'], ['use-cases', 'Use cases'],
  ['documents', 'Documents'], ['security', 'Security']]

const STRIP = [
  ['target', 'Accurate & cited answers', 'Every answer names the document, version, section and page it came from.'],
  ['layers', 'Complete traceability', 'Every sign-in, question and admin action is recorded in a hash-chained audit trail.'],
  ['users', 'Role-based access', 'Viewer, QA user, auditor and admin roles, enforced by the server on every request.'],
  ['server', 'On-premise & private', 'The language model, search indexes and database all run on your own machine.'],
]

const FEATURES = [
  ['chat', 'Conversational Q&A', 'Ask in plain language; follow-up questions understand the earlier ones.'],
  ['documents', 'Source-linked answers', 'The passages behind the answer appear before it is written; every [n] opens its source.'],
  ['info', 'Says when it doesn’t know', 'If the approved documents don’t cover a question, it says so instead of guessing.'],
  ['shield', 'Tamper-evident audit trail', 'A hash chain links every record; one click verifies that nothing was changed.'],
  ['layers', 'Controlled versions', 'A registry of document versions with SHA-256 fingerprints; superseded sources are flagged.'],
  ['users', 'Roles & access control', 'Least-privilege roles, account lockout, password rules and session limits.'],
  ['lock', 'Designed to support compliance', 'Built around 21 CFR Part 11 and EU GMP Annex 11 expectations for records and access.'],
  ['sparkle', 'FMCG / GMA', 'Consumer-health and FMCG quality environments.', 'Roadmap'],
]

const STEPS = [
  ['documents', '1. Register', 'Approved guidance and SOPs are registered with their version and fingerprint.'],
  ['layers', '2. Index', 'Passages are indexed for keyword and meaning search, then re-ranked.'],
  ['chat', '3. Ask', 'The local model writes an answer from the best passages only.'],
  ['shield', '4. Verify & trace', 'Check the cited passages; every question is in the audit trail.'],
]

const USE_CASES = [
  ['uc-lab.jpg', 'Scientist in a laboratory inspecting a vial', 'flask', 'Deviation & OOS handling',
    'Find what GMP guidance and your SOPs require for investigations and CAPA.'],
  ['uc-clipboard.jpg', 'Checklist on a clipboard', 'layers', 'SOP & process guidance',
    'Reach the approved procedure and the version that is in force.'],
  ['uc-vials.jpg', 'Vials on a production line', 'shield', 'Quality reviews & audits',
    'Prepare for inspections with cited answers and a complete record of what was asked.'],
]

function Brand() {
  return (
    <span className="flex items-center gap-3">
      <span className="grid h-11 w-11 place-items-center rounded-2xl bg-gradient-to-br from-blue-100 to-blue-200 text-primary shadow-[inset_0_1px_0_#fff,0_4px_10px_rgb(37_99_235/0.15)]">
        <Icon name="flask" size={22} />
      </span>
      <span className="leading-tight">
        <span className="block font-semibold">GMP Assistant</span>
        <span className="block text-xs text-muted">Quality Knowledge System</span>
      </span>
    </span>
  )
}

function Label({ children }) {
  return <span className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">{children}</span>
}

/** A still picture of the chat screen (an illustration, not live data). */
function ProductPreview() {
  const src = (n, code, title, section, version, fictional) => (
    <div className="mt-2 rounded-xl border border-slate-200 bg-white p-2.5">
      <div className="flex items-start gap-2">
        <span className="rounded-md bg-primary-subtle px-1.5 text-[10px] font-bold text-primary-ink">[{n}]</span>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 font-mono text-[11px] font-bold">{code}
            {fictional && <span className="rounded-full bg-fictional-bg px-1.5 font-sans text-[9px] font-medium text-fictional">Fictional</span>}
          </div>
          <div className="truncate text-[10px] text-muted">{title}</div>
          <div className="mt-1 flex gap-1 text-[9.5px]">
            <span className="rounded bg-primary-subtle px-1 text-primary-ink">§ {section}</span>
            <span className="rounded bg-info-bg px-1 text-info">{version}</span>
          </div>
        </div>
      </div>
    </div>
  )
  return (
    <div aria-hidden className="overflow-hidden rounded-[20px] border border-[#dfe7f6] bg-white/95 text-[11.5px] shadow-[0_40px_80px_-30px_rgb(30_64_175/0.35),0_10px_30px_rgb(15_23_42/0.08)]">
      <div className="flex items-center gap-3 border-b border-slate-100 px-4 py-2.5">
        <span className="flex gap-1.5">
          <i className="block h-2.5 w-2.5 rounded-full bg-red-400" /><i className="block h-2.5 w-2.5 rounded-full bg-amber-400" />
          <i className="block h-2.5 w-2.5 rounded-full bg-emerald-400" />
        </span>
        <span className="font-semibold">GMP Assistant</span>
        <span className="ml-3 hidden gap-1 sm:flex">
          {['Chat', 'History', 'Documents', 'Audit'].map((t, i) => (
            <span key={t} className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${i === 0 ? 'bg-primary text-white' : 'text-slate-600'}`}>{t}</span>
          ))}
        </span>
        <span className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-green-200 bg-success-bg px-2 py-0.5 text-[10.5px] text-success">
          <span className="h-1.5 w-1.5 rounded-full bg-green-600" />Ready
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[23%_1fr_30%]">
        <div className="hidden border-r border-slate-100 p-3 md:block">
          <div className="rounded-lg bg-primary py-1.5 text-center font-semibold text-white">+ New chat</div>
          <div className="mt-3 text-[10px] font-semibold uppercase tracking-wider text-muted">Today</div>
          <div className="mt-1 truncate rounded-lg bg-primary-subtle px-2 py-1.5 font-medium text-primary-ink">What must happen after an OOS…</div>
          <div className="mt-1 truncate px-2 py-1.5 text-slate-600">How often is a PQR required?</div>
          <div className="mt-2 text-[10px] font-semibold uppercase tracking-wider text-muted">Earlier</div>
          <div className="mt-1 truncate px-2 py-1.5 text-slate-600">Annex 11 audit trails</div>
        </div>
        <div className="border-r border-slate-100 p-3.5">
          <div className="ml-auto w-fit rounded-xl bg-slate-100 px-3 py-2 font-medium">What must happen after an OOS result?</div>
          <div className="mt-3 rounded-xl border border-slate-200">
            <p className="p-3 leading-relaxed text-slate-800">
              Any out-of-specification result should be investigated and documented according to a
              procedure <span className="rounded bg-primary-subtle px-1 text-[9.5px] font-bold text-primary-ink">[1]</span>.
              At Acme, the OOS SOP defines how the investigation is run and closed{' '}
              <span className="rounded bg-primary-subtle px-1 text-[9.5px] font-bold text-primary-ink">[2]</span>.
            </p>
            <div className="bg-success-bg px-3 py-1.5 text-success">Verify against the cited source before acting.</div>
            <div className="flex gap-3 px-3 py-1.5 text-[10px] text-muted"><span>👍</span><span>👎</span><span className="ml-auto">Copy answer</span></div>
          </div>
          <div className="mt-3 rounded-xl border border-slate-200 px-3 py-2 text-slate-400">Ask a question about GMP or SOPs…</div>
        </div>
        <div className="hidden p-3 md:block">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">Sources (2)</div>
          {src(1, 'ICH-Q7', 'GMP Guide for Active Pharmaceutical Ingredients', '11.15', 'Step 4, 2000')}
          {src(2, 'ACME-SOP-QC-007', 'Out-of-Specification (OOS) Investigation', '5', 'v3.0', true)}
        </div>
      </div>
    </div>
  )
}

export default function Welcome() {
  const { user } = useAuth()
  const cta = user
    ? { to: landingFor(user), text: 'Open the app' }
    : { to: '/login', text: 'Sign in' }
  const primary = 'inline-flex items-center gap-2 rounded-full bg-primary px-6 py-2.5 text-[15px] font-medium text-white shadow-[0_6px_16px_rgb(37_99_235/0.28)] hover:bg-primary-hover'
  const ghost = 'inline-flex items-center gap-2 rounded-full border border-line bg-white px-6 py-2.5 text-[15px] font-medium text-ink shadow-sm hover:bg-surface-muted'
  return (
    <div className="min-h-full bg-[#f3f6fd] [background-image:radial-gradient(900px_520px_at_72%_-8%,#d6e4ff_0%,transparent_62%),radial-gradient(700px_600px_at_-10%_30%,#e3ecff_0%,transparent_60%),radial-gradient(800px_500px_at_100%_55%,#e6eeff_0%,transparent_60%)]">
      <header className="sticky top-0 z-20 bg-[#f3f6fd]/80 backdrop-blur-md">
        <div className="mx-auto flex h-[74px] max-w-[1400px] items-center gap-7 px-[clamp(16px,3.2vw,44px)]">
          <Link to="/welcome" aria-label="GMP Assistant home"><Brand /></Link>
          <nav aria-label="Sections" className="hidden flex-1 justify-center gap-8 lg:flex">
            {SECTIONS.map(([id, label]) => (
              <a key={id} href={`#${id}`} className="text-[14.5px] font-medium hover:text-primary">{label}</a>
            ))}
          </nav>
          <Link to={cta.to} className={`${primary} ml-auto lg:ml-0`}>{cta.text}</Link>
        </div>
      </header>

      <main>
        {/* hero */}
        <section className="relative overflow-hidden">
          <img src="/landing/hero-line.jpg" alt="" className="absolute bottom-0 left-[max(0px,calc((100vw-1400px)/2-90px))] hidden h-[clamp(170px,16vw,240px)] w-[min(42vw,560px)] object-cover object-left [mask-image:linear-gradient(90deg,#000_55%,transparent),linear-gradient(0deg,#000_75%,transparent)] [mask-composite:intersect] xl:block" />
          <div className="relative mx-auto grid max-w-[1400px] items-start gap-9 px-[clamp(16px,3.2vw,44px)] pt-7 xl:grid-cols-[35%_1fr]">
            <div>
              <span className="mt-4 inline-flex items-center gap-2 rounded-full border border-[#dbe5f7] bg-white/75 px-3.5 py-1.5 text-sm">
                <Icon name="shield" className="text-primary" /> Pharma · GMP · SOP · Compliance
              </span>
              <h1 className="mb-4 mt-6 text-[clamp(32px,2.95vw,46px)] font-bold leading-[1.08] tracking-tight">
                Your <span className="text-primary">GMP &amp; SOP</span><br />Knowledge Assistant
              </h1>
              <p className="text-[clamp(15px,1.15vw,17px)] text-slate-700">
                A secure, on-premise assistant for pharma QA and compliance teams. Ask a question and get
                an answer from GMP guidance and your internal SOPs, with the exact passages it is based on
                and a tamper-evident record of every question.
              </p>
              <div className="mt-7 flex flex-wrap gap-3">
                <Link to={cta.to} className={primary}>{cta.text} <Icon name="arrowRight" /></Link>
                <a href="#how" className={ghost}>How it works</a>
              </div>
              <div className="hidden h-[clamp(150px,14vw,210px)] xl:block" />
            </div>
            <figure>
              <ProductPreview />
              <figcaption className="mt-2 text-center text-xs text-muted">Illustration of the chat screen.</figcaption>
            </figure>
          </div>
        </section>

        {/* feature strip */}
        <div id="security" className="relative z-10 mx-auto my-16 grid max-w-[calc(1400px-88px)] gap-6 rounded-[20px] border border-[#e3eaf7] bg-white/90 px-3 py-7 shadow-sm sm:grid-cols-2 xl:-mt-2 xl:grid-cols-4"
          style={{ width: 'calc(100% - 2 * clamp(16px, 3.2vw, 44px))' }}>
          {STRIP.map(([icon, title, text], i) => (
            <div key={title} className={`flex items-start gap-4 px-6 ${i ? 'xl:border-l xl:border-[#e5ebf5]' : ''}`}>
              <Icon name={icon} size={34} className="shrink-0 text-primary" />
              <div><h2 className="mb-1 text-[15.5px] font-semibold">{title}</h2><p className="text-[13px] text-muted">{text}</p></div>
            </div>
          ))}
        </div>

        <div className="mx-auto max-w-[1400px] px-[clamp(16px,3.2vw,44px)]">
          {/* features */}
          <section id="features" className="mb-20 scroll-mt-24">
            <Label>Features</Label>
            <h2 className="mb-2 mt-2 text-[clamp(28px,2.8vw,40px)] font-bold leading-tight tracking-tight">Everything your QA &amp; compliance teams need</h2>
            <p className="mb-7 text-slate-600">Made to keep GMP and SOP knowledge accessible, traceable and audit-ready.</p>
            <div className="grid gap-[18px] sm:grid-cols-2 xl:grid-cols-4">
              {FEATURES.map(([icon, title, text, tag]) => (
                <div key={title} className="rounded-[18px] border border-[#e3eaf7] bg-white/80 p-[22px] shadow-sm">
                  <Icon name={icon} size={28} className="text-primary" />
                  <h3 className="mb-1.5 mt-4 text-[17.5px] font-semibold">
                    {title}
                    {tag && <span className="ml-2 rounded-full border border-line bg-slate-100 px-2 py-px align-middle text-[10px] font-semibold text-muted">{tag}</span>}
                  </h3>
                  <p className="text-sm text-slate-600">{text}</p>
                </div>
              ))}
            </div>
          </section>

          {/* how it works */}
          <section id="how" className="mb-20 grid scroll-mt-24 items-start gap-10 xl:grid-cols-[28%_1fr]">
            <div>
              <Label>How it works</Label>
              <h2 className="mb-2 mt-2 text-[clamp(28px,2.8vw,40px)] font-bold leading-tight tracking-tight">From your SOPs to trusted answers</h2>
              <p className="mb-6 text-slate-600">Retrieval first, then a local language model that may only use what was retrieved.</p>
              <Link to={cta.to} className={primary}>{cta.text}</Link>
            </div>
            <ol className="grid items-center gap-3.5 sm:grid-cols-2 xl:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
              {STEPS.map(([icon, title, text], i) => (
                <li key={title} className="contents">
                  {i > 0 && <Icon name="arrowRight" size={22} className="hidden text-muted xl:block" />}
                  <div className="h-full rounded-[18px] border border-[#e3eaf7] bg-white/85 px-[18px] py-[22px] text-center shadow-sm">
                    <span className="mx-auto grid h-[54px] w-[54px] place-items-center rounded-2xl bg-white text-primary shadow-[0_8px_18px_rgb(37_99_235/0.14),inset_0_0_0_1px_#e6edfa]">
                      <Icon name={icon} size={26} />
                    </span>
                    <h3 className="mb-1.5 mt-4 text-[16.5px] font-semibold">{title}</h3>
                    <p className="text-sm text-slate-600">{text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          {/* use cases */}
          <section id="use-cases" className="mb-20 grid scroll-mt-24 items-start gap-10 xl:grid-cols-[28%_1fr]">
            <div>
              <Label>Use cases</Label>
              <h2 className="mb-2 mt-2 text-[clamp(28px,2.8vw,40px)] font-bold leading-tight tracking-tight">Designed for real-world quality &amp; compliance work</h2>
              <p className="text-slate-600">Day-to-day questions from QA, QC and compliance teams in pharma manufacturing.</p>
            </div>
            <div className="grid gap-5 md:grid-cols-3">
              {USE_CASES.map(([img, alt, icon, title, text]) => (
                <div key={title} className="overflow-hidden rounded-[18px] border border-[#e3eaf7] bg-white/90 shadow-sm">
                  <div className="relative h-[190px]">
                    <img src={`/landing/${img}`} alt={alt} className="h-full w-full object-cover" />
                    <span className="absolute -bottom-[22px] left-4 grid h-[46px] w-[46px] place-items-center rounded-full bg-white text-primary shadow-md">
                      <Icon name={icon} size={22} />
                    </span>
                  </div>
                  <div className="px-5 pb-[22px] pt-8">
                    <h3 className="mb-1.5 text-lg font-semibold">{title}</h3>
                    <p className="text-sm text-slate-600">{text}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* documents */}
          <section id="documents" className="mb-20 scroll-mt-24">
            <Label>Documents</Label>
            <h2 className="mb-2 mt-2 text-[clamp(28px,2.8vw,40px)] font-bold leading-tight tracking-tight">What the assistant knows</h2>
            <p className="mb-7 text-slate-600">
              {PUBLIC_GUIDANCE.length + FICTIONAL_SOPS.length} controlled documents: {PUBLIC_GUIDANCE.length} public
              regulatory guidance documents and {FICTIONAL_SOPS.length} SOPs of Acme Pharma Ltd., a fictional company
              used to demonstrate internal procedures.
            </p>
            <div className="grid gap-5 lg:grid-cols-2">
              {[['Public guidance', PUBLIC_GUIDANCE, false], ['Internal SOPs', FICTIONAL_SOPS, true]].map(([heading, docs, fictional]) => (
                <div key={heading} className="rounded-[18px] border border-[#e3eaf7] bg-white/85 p-5 shadow-sm">
                  <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted">
                    {heading}{fictional && <FictionalTag />}
                  </h3>
                  <ul className="space-y-1.5">
                    {docs.map(([code, title]) => (
                      <li key={code} className="flex gap-3 text-sm">
                        <code className="w-40 shrink-0 font-mono text-[12.5px] font-bold">{code}</code>
                        <span className="text-slate-600">{title}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>

          {/* call to action */}
          <section className="relative grid min-h-[190px] items-center gap-7 overflow-hidden rounded-[26px] bg-gradient-to-r from-[#3b6ff5] via-[#5b8cf7] to-[#c9dafb] px-[clamp(22px,4vw,52px)] py-11 text-white shadow-[0_24px_50px_-24px_rgb(37_99_235/0.55)] lg:grid-cols-[minmax(0,1fr)_auto_24%]">
            <div className="relative z-[1]">
              <h2 className="mb-3 text-[clamp(24px,2.3vw,32px)] font-bold leading-tight">Ready to ask your first question?</h2>
              <p className="max-w-[460px] opacity-95">Sign in with the account your administrator created for you.</p>
            </div>
            <div className="relative z-[1]">
              <Link to={cta.to} className="inline-flex items-center gap-2 rounded-full bg-blue-700 px-6 py-2.5 font-medium text-white hover:bg-blue-800">
                {cta.text} <Icon name="arrowRight" />
              </Link>
            </div>
            <img src="/landing/cta-vials.jpg" alt="" className="absolute right-0 top-0 h-full w-full object-cover opacity-30 [mask-image:linear-gradient(90deg,transparent_0%,#000_40%)] lg:w-[42%] lg:opacity-100" />
          </section>

          <footer className="mt-14 flex flex-wrap justify-between gap-4 border-t border-[#d7deee] pb-10 pt-7 text-[13px] text-muted">
            <span>GMP Assistant · on-premise. Answers must be verified against the cited source; not a substitute for quality review.</span>
            <span>Acme Pharma Ltd. and its SOPs are fictional.</span>
          </footer>
        </div>
      </main>
    </div>
  )
}
