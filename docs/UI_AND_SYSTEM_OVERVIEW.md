# UI and System Overview — Pharma GMP SOP Assistant

**Purpose:** a design brief. It explains what the product does, which screens and components exist, what data each one shows and every state it can be in, so the UI can be designed without reading the whole spec.
**Authority:** `PROJECT_SPEC.md` v6.0. Section references like (§17) point there. If this file and the spec disagree, the spec wins.

---

## 1. What we're building, in one paragraph

A secure, on-premise web app for pharma QA and compliance staff. They log in, ask a question about GMP regulations or internal SOPs, and watch a cited answer being written in real time. Next to the answer they see the exact passages it came from: document, version, section and page. If the documents don't cover the question, the app says so instead of guessing. Every login, question and admin action is recorded in a tamper-evident audit trail that auditors can review and verify. Everything (the AI model, search indexes and database) runs on one machine.

---

## 2. Who uses it

| Role | Who they are | What they do in the app |
|---|---|---|
| **Viewer** | Operators, junior QA staff | Ask questions, read answers, see own history |
| **QA user** | QA / compliance engineers | Same as viewer; manage documents in Tier 2 |
| **Auditor** | Internal audit, QA oversight, inspectors | **Cannot ask questions.** Reviews the audit trail, verifies integrity, exports records |
| **Admin** | System owner / IT | Everything a QA user can do, plus user management and system health |

Design for **desktop first** (office workstations, 1366–1920 px wide). Laptops at 1280 px must work. Mobile isn't a target.

---

## 3. Screen map

```
                         ┌──────────┐
                         │  Login   │
                         └────┬─────┘
                              │ first login / expired password
                              ▼
                     ┌──────────────────┐
                     │ Change password  │
                     └────────┬─────────┘
                              │
       ┌──────────────────────┼─────────────────────────┐
       │ viewer, qa_user, admin                          │ auditor
       ▼                                                  ▼
 ┌───────────┐   ┌───────────┐   ┌─────────────┐   ┌─────────────┐
 │   Chat    │   │  History  │   │  Documents  │   │ Audit trail │
 │    (/)    │   │ (/history)│   │(/documents) │   │  (/audit)   │
 └───────────┘   └───────────┘   └─────────────┘   └─────────────┘
                                                         ▲
                                         admin also sees │
                                       ┌─────────────────┴──┐
                                       │ Users (/admin/users)│
                                       │ System health panel │
                                       └─────────────────────┘
```

### Navigation by role

| Menu item | Viewer | QA user | Auditor | Admin |
|---|:-:|:-:|:-:|:-:|
| Chat | ✅ | ✅ | — | ✅ |
| History | ✅ (own) | ✅ (own) | — | ✅ (own) |
| Documents | ✅ | ✅ | ✅ | ✅ |
| Audit trail | — | — | ✅ (landing page) | ✅ |
| Users | — | — | — | ✅ |
| System health | — | — | — | ✅ (in user menu or Users page) |

The auditor lands on **Audit trail**; everyone else lands on **Chat**.

---

## 4. Global layout

### 4.1 App shell (all signed-in pages)

```
┌───────────────────────────────────────────────────────────────────────────┐
│ [Logo] GMP Assistant   Chat  History  Documents  Audit  Users    ● Ready  👤▾│  ← Top bar
├───────────────────────────────────────────────────────────────────────────┤
│ [Integrity banner — only when audit verification failed]                  │  ← Global banners
│ [System banner — only when LLM offline / index not ready]                 │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│                              Page content                                 │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Top bar components

| Component | Content | States |
|---|---|---|
| **Logo + product name** | "GMP Assistant" | — |
| **Nav links** | Filtered by role (§3) | default, hover, active |
| **System status pill** | `● Ready` / `● Degraded` / `● Not ready` | green / amber / red; tooltip explains (e.g. "AI model offline") |
| **User menu** | Full name, role badge | Opens: Change password, System health (admin), Sign out |

### 4.3 Global banners

| Banner | Shown to | When | Tone |
|---|---|---|---|
| **Integrity banner** | auditor, admin | Last audit verification failed | Red, persistent, "View details" → Audit page |
| **System banner** | everyone | `/api/health` is degraded or not ready | Amber (degraded) / red (not ready), plain-language message |
| **Session expiry warning** | everyone | 2 minutes before idle timeout | Neutral, "Stay signed in" button |
| **Toast notifications** | everyone | Success/error after actions (user created, export ready, feedback saved) | Auto-dismiss 5 s; errors stay until closed |

---

## 5. Screens

### 5.1 Login

**Components:** product name and one-line description · username field · password field (show/hide toggle) · Sign in button · footer: "Authorised users only. All activity is recorded."

| State | What the user sees |
|---|---|
| Default | Empty form |
| Submitting | Button spinner, fields disabled |
| Wrong credentials | Inline error: "Username or password is incorrect." (same message for unknown users, on purpose) |
| Account locked | "Account locked after too many attempts. Try again in 30 minutes or contact your administrator." |
| Rate limited | "Too many attempts. Wait a minute and try again." |
| Deactivated account | Same as wrong credentials (don't reveal account status) |
| Server unreachable | "Can't reach the server." |

### 5.2 Change password

Shown on first login, when the password has expired, or from the user menu.

**Components:** current password · new password · confirm · live rule checklist (✓/✗):
- at least 12 characters
- not a common password (checked on submit)
- not one of your last 5 passwords (checked on submit)
- both entries match

| State | Behaviour |
|---|---|
| Forced (first login / expired) | No way to skip; navigation hidden; explanation text at top |
| Voluntary | Cancel button available |
| Rule fails on submit | Inline message on the failing rule |
| Success | Toast; forced flow continues to the landing page |

### 5.3 Chat (main screen)

Three columns:

```
┌────────────────┬──────────────────────────────────────┬──────────────────┐
│ CONVERSATIONS  │ CONVERSATION                          │ SOURCES          │
│ 240 px         │ flexible                              │ 360 px           │
│                │                                       │                  │
│ [+ New chat]   │  ┌ Question bubble ────────────────┐  │ ┌ Source card ─┐ │
│                │  └─────────────────────────────────┘  │ │ [1] ICH-Q7   │ │
│ Today          │  ┌ Answer block ───────────────────┐  │ │ §11.15 p.33  │ │
│  ▸ OOS & CAPA  │  │ status line / streaming text    │  │ │ Step 4, 2000 │ │
│  ▸ Audit trail │  │ citation badges [1] [2]         │  │ │ "passage…"   │ │
│ Earlier        │  │ ⚠ verify notice                 │  │ └──────────────┘ │
│  ▸ PQR freq.   │  │ 👍 👎   · 64 s · Copy           │  │ ┌ Source card ─┐ │
│                │  └─────────────────────────────────┘  │ │ [2] SOP-QC-… │ │
│                │                                       │ └──────────────┘ │
│                ├───────────────────────────────────────┤                  │
│                │ [ Ask a question about GMP or SOPs… ] │                  │
│                │  0/1000                       [Send]  │                  │
└────────────────┴───────────────────────────────────────┴──────────────────┘
```

Below 1280 px: the conversations column collapses to an icon, and Sources becomes a drawer that opens when a citation is clicked.

#### Components

| Component | Content | Notes |
|---|---|---|
| **Conversation list** | "New chat" button; conversations grouped Today / Yesterday / Earlier; title = first question, truncated | Active item highlighted. No rename/delete (records are kept). |
| **Empty state** | Short intro + 4 example question chips (e.g. "What must happen after an OOS result?", "How often is a Product Quality Review required?", "What does Annex 11 say about audit trails?", "Does our deviation SOP align with ICH Q10?") | Clicking a chip sends it |
| **Question bubble** | User's question, timestamp | Right-aligned or clearly distinct from answers |
| **Answer block** | Status line → streamed text → citation badges → footer | See states below |
| **Citation badge `[n]`** | Inline clickable marker in answer text | Hover: tooltip with doc code + section. Click: scrolls to and highlights source card *n* |
| **Verify notice** | "Verify against the cited source before acting." | On **every** answered response; subtle but always visible |
| **Answer footer** | 👍 👎 · total time (e.g. "64 s") · Copy answer | 👎 opens a small comment box (optional, max 1000 chars) |
| **Citation warning badge** | Amber "Some citations couldn't be verified" | Only when the citation check flags a problem |
| **Composer** | Multi-line input, character counter (max 1000), Send button | Enter = send, Shift+Enter = new line. Disabled while this user's question is running. |
| **Source card** | Number badge `[n]` · document code + title · version · section number + title · page (PDFs) · passage text (collapsed to 5 lines, "Show more") · "Fictional" tag for Acme SOPs | Highlight state when its citation is clicked |
| **Sources header** | "Sources (4)", and below: "Only these passages were used to write the answer." | — |

#### Answer states (important — design each one)

Each answer moves through these states. Data comes from the stream events (§17).

| # | State | Trigger | What to show |
|---|---|---|---|
| 1 | **Queued** | `queued` event | "Waiting — 2 questions ahead of you" + subtle progress animation |
| 2 | **Understanding follow-up** | `status: rewriting` | "Understanding your question…" (only for follow-ups) |
| 3 | **Searching** | `status: retrieving` / `reranking` | "Searching 19 documents…" |
| 4 | **Sources ready** | `sources` event | Sources column fills **before** the answer starts; answer area shows "Writing answer…" |
| 5 | **Streaming** | `token` events | Text appears word by word with a blinking cursor; citation badges become clickable as they appear |
| 6 | **Answered** | `done`, `answer_type: answered` | Full answer, verify notice, footer with feedback and time |
| 7 | **Not covered** | `done`, `answer_type: retrieval_refusal` or `model_refusal` | Neutral info style (not an error): "The approved documents don't cover this question." + tip to rephrase. No verify notice; feedback still allowed. |
| 8 | **Answered with citation warning** | `done` with citation problem | State 6 + amber warning badge |
| 9 | **Error** | `error` event or network failure | Red inline block with plain message + "Try again" + small reference ID (`request_id`) |
| 10 | **Not recorded** | `error: AUDIT_WRITE_FAILED` | Answer hidden; "This answer couldn't be recorded, so it wasn't shown. Please try again." |
| 11 | **Interrupted** | User navigates away or loses connection mid-stream | Partial text greyed out + "Answer interrupted" + "Ask again" |

Expected timings on the target laptop: states 1–4 take a few seconds to ~30 s; streaming (state 5) takes 30–60 s. The status line must always show progress so the screen never looks frozen.

### 5.4 History

**Purpose:** a user's own past questions (admins see their own here; everyone's is in Audit).

**Components:**
- Search box (question text) · date range picker
- Table: Date/time · Question (truncated) · Result type (Answered / Not covered / Failed) · Sources count · Feedback (👍/👎/—) · Time taken
- Pagination (20 per page)
- **Detail drawer** (click a row): full question, standalone question if rewritten, full answer with citations, source cards, documents' versions *at the time of the answer*, feedback

| State | What to show |
|---|---|
| Empty | "No questions yet." + link to Chat |
| Loading | Skeleton rows |
| Superseded source | In the detail drawer, a "Superseded" tag on a source whose document version is no longer active, with "answered using version X" |

### 5.5 Documents

**Purpose:** show which documents and versions the assistant answers from.

**Components:**
- Summary strip: total active documents · total passages indexed · index build date · embedding model name
- Filter: status (Active / Superseded / Withdrawn) · type (Public guidance / Internal SOP) · search
- Table: Document code · Title · Version · Effective date · Publisher · Status badge · Passages (chunk count) · Ingested on
- **Detail drawer:** all metadata incl. SHA-256 fingerprint (monospace, copy button), version history for that document code (timeline: active ← superseded ← superseded), "Fictional document" notice for Acme SOPs

**Tier 2 additions to reserve space for (qa_user, admin):**
- "Upload document" button → form: file (PDF), document code, title, version, effective date, publisher; "this replaces version X" confirmation
- "Withdraw" action with mandatory reason
- Indexing progress state: "Rebuilding search index… documents remain searchable on the previous version until finished."

### 5.6 Audit trail (auditor, admin)

**Purpose:** review and verify every recorded action.

**Components:**
- **Integrity panel** (top): last verification time · result (✅ "Chain intact — 12,431 records" / ❌ "Broken at record #8,214") · **Verify now** button
- **Filters:** date-time range · user · event type (multi-select, grouped: Access, Queries, Documents, Users, System) · result (success/failure)
- **Table:** # (sequence) · Time (UTC, with local time on hover) · User · Role · Event type (badge) · Summary (generated one-liner, e.g. "Asked: When must a CAPA…", "Login failed: wrong password", "Role changed: viewer → qa_user") · IP
- **Detail drawer:** all fields; payload rendered as readable key–value sections (for `QUERY`: question, answer, sources with versions, scores, timings); raw JSON toggle; hash and previous hash (monospace, truncated with copy)
- **Export:** "Export JSON" for the current filter (Tier 1); CSV in Tier 2. Export confirmation shows the record count; the export itself is audited.
- Pagination (50 per page), newest first

| State | What to show |
|---|---|
| Verifying | Integrity panel spinner + "Checking 12,431 records…" |
| Verification failed | Red panel, the broken record number, link to jump to it; global integrity banner appears |
| Empty filter result | "No records match these filters." |

**Event-type badge groups** (pick one colour family per group):

| Group | Events |
|---|---|
| Access | LOGIN_SUCCESS, LOGIN_FAILED, ACCOUNT_LOCKED, LOGOUT, PASSWORD_CHANGED, ACCESS_DENIED, REFRESH_REUSE_DETECTED |
| Queries | QUERY, QUERY_FAILED, FEEDBACK |
| Documents | DOCUMENT_INGESTED, DOCUMENT_SUPERSEDED, DOCUMENT_WITHDRAWN, INDEX_BUILT, INDEX_ACTIVATED |
| Users | USER_CREATED, USER_ROLE_CHANGED, USER_DEACTIVATED |
| System | SYSTEM_START, AUDIT_VERIFIED, AUDIT_EXPORTED |

Failures (LOGIN_FAILED, ACCESS_DENIED, QUERY_FAILED, REFRESH_REUSE_DETECTED) also get a red marker.

### 5.7 Users (admin)

**Components:**
- "Add user" button
- Table: Username · Full name · Role (badge) · Status (Active / Locked / Deactivated / Must change password) · Last login · Created on · Actions (⋯)
- **Add user dialog:** username, full name, role (select with one-line description of each role) → result screen shows a **temporary password once** with a copy button and "The user must change it at first sign-in."
- **Row actions:** Change role (confirm dialog showing before → after) · Unlock · Deactivate (confirm; explains that users are never deleted and their records are kept)

| Rule to reflect in UI | How |
|---|---|
| Admin can't change own role or deactivate self | Actions disabled on own row with tooltip |
| At least one active admin must remain | Deactivating/demoting the last admin is disabled with tooltip |
| Usernames can't be reused | Error message on create if taken, including by deactivated users |

### 5.8 System health (admin)

A panel or small page with cards:

| Card | Shows |
|---|---|
| AI model | Ollama reachable ✅/❌ · model name · loaded in memory |
| Search index | Build ID · build date · passages · embedding model · reranker model |
| Documents | Active count; list of active versions |
| Audit trail | Last verification time and result |
| Storage | Free disk space |
| Version | App version, git commit |

---

## 6. Shared UI components (component inventory)

| Component | Used in |
|---|---|
| AppShell (top bar, nav, user menu, banners) | All signed-in pages |
| StatusPill | Top bar, Health |
| Banner (info / warning / error) | Global, Chat |
| Toast | Global |
| Button (primary, secondary, ghost, danger) | Everywhere |
| TextInput, PasswordInput, TextArea with counter, Select, MultiSelect, DateRangePicker, SearchBox | Forms, filters |
| DataTable (sortable headers, pagination, row click, empty/loading/error states) | History, Documents, Audit, Users |
| Drawer (right side, wide) | History, Documents, Audit details |
| Dialog / ConfirmDialog | Users, exports, withdraw |
| Badge (role, status, event type, document status, "Fictional") | Everywhere |
| Skeleton loaders | Tables, chat history |
| ConversationList | Chat |
| QuestionBubble, AnswerBlock, StatusLine, StreamingText, CitationBadge, FeedbackButtons | Chat |
| SourceCard, SourcePanel | Chat, History detail |
| IntegrityPanel | Audit |
| KeyValueList, CodeValue (monospace + copy) | Detail drawers |
| PasswordRulesChecklist | Change password |

---

## 7. Data the UI receives (for realistic mockups)

### 7.1 Current user (`GET /api/me`)
```json
{"id": "u_12", "username": "gpatil", "full_name": "Gaurav Patil", "role": "qa_user",
 "permissions": ["query:run", "history:own", "docs:read", "docs:manage"],
 "must_change_password": false}
```

### 7.2 Source (stream `sources` event and query detail)
```json
{"n": 1, "doc_code": "ICH-Q7",
 "title": "Good Manufacturing Practice Guide for Active Pharmaceutical Ingredients",
 "version": "Step 4, 10 Nov 2000", "section": "11.15", "section_title": "Out-of-Specification Results",
 "page": 33, "text": "Out-of-specification results should be investigated and documented…",
 "is_fictional": false}
```

### 7.3 Answer completion (stream `done` event)
```json
{"event_id": "evt_01J…", "answer_type": "answered",
 "citation_check": {"status": "ok", "invalid": [], "uncited": false},
 "latency_ms": {"retrieval": 180, "rerank": 950, "ttft": 21000, "total": 64000}}
```

### 7.4 Document row (`GET /api/documents`)
```json
{"id": "d_3", "doc_code": "ACME-SOP-QC-007", "title": "Out-of-Specification (OOS) Investigation",
 "version": "3.0", "effective_date": "2026-01-15", "publisher": "Acme Pharma Ltd. (fictional)",
 "status": "active", "chunk_count": 41, "sha256": "9f2c…e81a", "ingested_at": "2026-11-21T09:14:03Z"}
```

### 7.5 Audit row (`GET /api/audit/log`)
```json
{"seq": 8214, "timestamp_utc": "2026-11-21T10:02:44.512Z", "event_type": "QUERY",
 "username": "gpatil", "role": "qa_user", "client_ip": "192.168.1.24",
 "summary": "Asked: When must a CAPA be raised after an OOS result?",
 "row_hash": "a41f…", "prev_hash": "77c0…"}
```

### 7.6 Realistic volumes for mockups
19 documents (7 public + 12 SOPs) · ~1,500–2,500 passages · conversations of 1–6 questions · answers of 80–250 words with 2–5 citations · audit log of thousands of rows.

---

## 8. Backend components (what powers each screen)

```
 React app ── HTTPS ──▶ Caddy (web) ──▶ FastAPI backend ──▶ Ollama (llama3.1:8b)
                                            │
                                            ├── Auth & permissions
                                            ├── Audit writer (hash chain)
                                            ├── RAG pipeline
                                            │     rewriter → hybrid search → reranker → generator → citation check
                                            ├── LLM queue (one question at a time)
                                            ├── Index manager (FAISS + BM25, safe swaps)
                                            └── SQLite: users, documents, conversations,
                                                         audit_log, feedback, sessions
```

| Backend component | What it does | Screens it powers |
|---|---|---|
| **Caddy (web tier)** | Serves the React app, HTTPS, forwards `/api` | All |
| **Auth service** | Login, tokens, password rules, lockout, sessions | Login, Change password, user menu, session expiry |
| **Permissions (RBAC)** | Decides what each role may do — enforced on every request | Navigation, every action |
| **Conversation service** | Groups questions; supplies the last 2 exchanges for follow-ups | Chat conversation list |
| **RAG pipeline** | Rewrites follow-ups → searches (keyword + semantic) → reranks → refuses or generates → checks citations | Chat answer + sources |
| **LLM queue** | One question runs at a time on CPU; reports queue position | Chat "Queued" state |
| **Streaming endpoint** | Sends status, sources, tokens and completion as events | Chat states 1–11 |
| **Audit writer** | Records every action with user identity; hash-chains entries; verifies integrity | Audit trail, History, integrity banner |
| **Document registry** | Document metadata, versions, status, fingerprints | Documents |
| **Index manager** | Holds the active search index; rebuilds and swaps without downtime | Documents summary, Health |
| **Feedback service** | Stores 👍/👎 and comments | Chat footer, History |
| **User management** | Create, change role, unlock, deactivate | Users |
| **Health service** | Checks model, index, audit status, disk | Status pill, banners, System health |

### Screen → API map

| Screen | Endpoints |
|---|---|
| Login / password | `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/change-password`, `GET /me` |
| Chat | `POST /conversations`, `POST /query/stream`, `POST /feedback`, `GET /history?conversation=…` |
| History | `GET /history`, `GET /history/{event_id}` |
| Documents | `GET /documents` (Tier 2: `POST /documents`, `POST /documents/{id}/withdraw`) |
| Audit trail | `GET /audit/log`, `POST /audit/verify`, `GET /audit/export` |
| Users | `GET /users`, `POST /users`, `PATCH /users/{id}` |
| Status / health | `GET /health`, `GET /health/details` |

---

## 9. Design guidance

- **Tone:** calm, clinical, trustworthy. This is a compliance tool, so prefer clarity over decoration. High information density on tables; generous spacing in chat.
- **Colour semantics (reserve these, don't use them decoratively):** green = OK/verified, amber = warning/degraded/citation issue, red = error/failure/integrity broken, neutral blue-grey = informational ("not covered" is informational, not an error).
- **Traceability is the hero:** source cards and citation badges deserve as much visual weight as the answer itself. A user should be able to go from any sentence to its source in one click.
- **Never hide uncertainty:** citation warnings, "not covered", the verify notice and superseded-version tags must always be visible, never hidden behind hover.
- **Monospace** for hashes, IDs, document codes in detail views.
- **Timestamps:** show local time; UTC on hover in Audit (records are stored in UTC).
- **Accessibility:** WCAG 2.1 AA contrast; full keyboard use (Tab order, Enter to send, Esc closes drawers); visible focus rings; status changes in chat announced to screen readers (`aria-live="polite"` on the status line); don't rely on colour alone (pair with icons/text).
- **Fictional content:** any Acme SOP shows a small "Fictional" tag wherever it appears.

### 9.1 Visual reference (mockups, 2026-11-20)

The approved look and feel is shown in these mockups. They define **style and layout only**. Where a mockup and this brief or `PROJECT_SPEC.md` disagree, the text wins (see the corrections in §9.3).

| File | Screen | Use |
|---|---|---|
| `docs/images/mockup_1_chat.png` | Chat (§5.3), state 6 "Answered" | Layout + style reference |
| `docs/images/mockup_2_documents.png` | Documents (§5.5) | Layout + style reference |
| `docs/images/mockup_3_history.png` | History (§5.4) | Layout + style reference |
| `docs/images/mockup_0_landing_style_only.png` | Marketing landing page | **Style only.** There is no landing page in PROJECT_SPEC §18.1; the app starts at `/login`. Not built. |

Screens without a mockup (Login, Change password, Audit trail, Users, System health, and chat states 1–5 and 7–11) use the same tokens and components below.

### 9.2 Style tokens

Colours are approximate values sampled from the mockups and mapped to the Tailwind CSS v4 default palette (PROJECT_SPEC §5.1). Define them once as theme variables (`@theme` in the main CSS file); components use the token names, never raw hex values.

| Token | Tailwind | Approx. hex | Used for |
|---|---|---|---|
| `canvas` | custom | `#ECF0FA` | Page background: very light blue-grey, with a soft blue gradient in the top-right corner |
| `surface` | `white` | `#FFFFFF` | Cards, panels, table containers, top bar |
| `surface-muted` | `slate-50` | `#F8FAFC` | Table header rows, question bubble, passage quote box |
| `border` | `slate-200` | `#E2E8F0` | 1 px card and table borders |
| `primary` | `blue-600` / hover `blue-700` | `#2563EB` | Primary buttons (Send, New chat), active nav pill, focus ring, links |
| `primary-subtle` | `blue-100` text `blue-700` | `#DBEAFE` | Active sidebar item, citation badges `[n]`, section chips `§ 11.15`, current page in pagination |
| `text` | `slate-900` | `#0F172A` | Headings, body text |
| `text-muted` | `slate-500` | `#64748B` | Subtitles, metadata, timestamps, table secondary lines |
| `success` | `green-50` bg, `green-700` text | `#F0FDF4` | Status pill "Ready" dot, "Active" status badge, "Answered" result, verify notice band |
| `warning` | `amber-50` bg, `amber-600` text | `#D97706` (dot) | "Superseded" badge, citation-warning badge, "Degraded" status, session-expiry banner |
| `danger` | `red-50` bg, `red-700` text | `#FEF2F2` | "Failed" result, error blocks, integrity banner, "Not ready" status |
| `info` | `slate-100` bg, `slate-700` text | `#F1F5F9` | "Not covered" result and refusal block (informational, not an error, and kept visibly distinct from the primary blue) |
| `fictional` | `violet-50` bg, `violet-700` text | `#F5F3FF` | "Fictional" tag, Acme SOP document icon |

**Shape and type**
- Cards: `rounded-2xl`, 1 px `border`, soft shadow (`shadow-sm`), 20–24 px padding. Buttons and inputs: `rounded-xl`. Badges and chips: `rounded-full` (status) or `rounded-md` (citation `[n]`, `§` chips).
- Font: a clean geometric sans (the mockups resemble Inter). The app is on-premise, so fonts must be **self-hosted or system fonts; no Google Fonts CDN at runtime**. Default: system stack `ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif`. A bundled Inter package is a new dependency and needs approval in M8.
- Sizes: page title 30–32 px bold; section label 12 px uppercase, letter-spaced, `text-muted` (e.g. "CONTROLLED KNOWLEDGE BASE"); body 15–16 px; table text 14 px.
- Monospace (`ui-monospace`) for hashes, IDs and request IDs (§9).
- Icons: one outline icon set at 1.5–2 px stroke, 20 px in nav and 16 px inline. Every status icon is paired with a text label (§9 accessibility).

**Layout patterns taken from the mockups**
- Top bar: logo tile (flask icon on `primary-subtle`) + "GMP Assistant / Quality Knowledge System", nav as pill-shaped tabs with the active one filled, then status pill and avatar with name and role on the right.
- Page header: small uppercase section label, then a large title, then a one-line muted description, with the page's primary action button aligned right.
- Documents: summary strip of 4 stat cards (icon tile, label, big number, muted sub-line) above a filter row (search + status dropdown + count) and the table.
- History: search + date range + Filters button row, then a table card with sortable headers and right-chevron rows that open the detail drawer.
- Chat: the three columns from §5.3. The answer sits in a white card with the verify notice as a full-width green band and the footer row (👍 👎 · ⏱ time · Copy answer) separated by a divider. The composer is a white card with a character counter and a primary Send button. Below the composer a muted line reads "Responses use approved documents only. Do not use as a substitute for quality review." The sidebar footer note reads "Conversations are retained for auditability."

### 9.3 Corrections to the mockups (text wins)

The mockups are illustrations; these details must **not** be copied as drawn:

| # | Mockup shows | Build instead | Reason |
|---|---|---|---|
| 1 | QA user sees **Audit Trail** and **Users** in the nav | Nav filtered by role: QA user sees Chat, History, Documents only | §3 navigation table; PROJECT_SPEC §18.1 |
| 2 | Embedding model card "**nomic-embed**" | The real `embedding_model` from the active index (`/health/details`); one of MiniLM / bge-small / e5-small or its fine-tuned variant | PROJECT_SPEC §5.4, D-11 / D-12 |
| 3 | Documents **21-CFR-211** and code **EU-GMP-ANNEX-11** | Only the §6.1 corpus with its exact codes (`EU-ANNEX11`, `FDA-P11-2003`, `FDA-PV-2011`, `ICH-Q9R1`, `WHO-GMP-MAIN`, …) | PROJECT_SPEC §6.1 |
| 4 | **Upload document** button | Not rendered in Tier 1 (Documents is read-only); keep the header slot free for Tier 2 | §5.5; PROJECT_SPEC §2.1, §18.1 |
| 5 | Red file icons for public guidance documents | Neutral (`slate`) icon for public documents; `fictional` violet for Acme SOPs | Red is reserved for errors (§9 colour semantics) |
| 6 | Green "All systems operational" banner | No banner when healthy; the status pill shows "Ready". Banners appear only when degraded / not ready | §4.3 |
| 7 | Notification bell with red dot | Omit; there is no notification feature | Not in §4.2 or PROJECT_SPEC |
| 8 | "**Grounded response**" badge | Omit, or show "Citations checked" **only** when the citation check passed (never alongside the state-8 warning badge) | Must not imply verification the system doesn't do; §5.3 states 6 and 8 |
| 9 | "Secure session" pill and "Source traceability ›" link | Omit; neither has a defined function | Not in §5.3 components |
| 10 | Conversation titled "Audit trail requirements" while its first question is about OOS | Title = first question, truncated | §5.3 conversation list |
| 11 | History "1–4 of 4 records" with a page 2 button; decorative illustration | 20 rows per page, pagination consistent with the count; illustration optional | §5.4; §9 clarity over decoration |
| 12 | "Not covered" in the same blue as primary actions | `info` token (blue-grey) | §9: informational, distinct from actions |
| 13 | Landing page ("Request Demo", "FMCG / GMA Ready") | Not built | Not in PROJECT_SPEC §18.1 |

---

## 10. Out of scope for the UI (don't design these)

- Dark mode (optional later)
- Mobile layouts
- Renaming or deleting conversations
- Editing answers
- Electronic signatures / approvals
- Chat with uploaded files (only the controlled corpus is searchable)
