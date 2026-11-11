# Gongwen Master

**An agent skill for writing Chinese official documents. Install it, describe what you need, and get a draft — every citation traceable to its source.**

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-8.1.10-green.svg)](VERSION)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776ab.svg)](requirements.txt)
[![Corpus](https://img.shields.io/badge/corpus-14%2C933%20docs-orange.svg)](DATA_LICENSE.md)

**English** | [简体中文](README.md)

---

## 1. What it is

A skill built from Markdown instructions plus a Python retrieval engine, installable in WorkBuddy, Claude, Doubao, and other platforms that support Agent Skills. Once installed, say "write a notice", "draft a speech for the director", "tighten this paragraph", or "quality-check this document" — the skill identifies the document type, loads the matching rules, and queries source texts when needed.

**It is not a prompt template.** A template hands you a paragraph to rewrite. This gives you 14,933 policy documents as a factual base, structural skeletons for 16 document types, and executable self-checks and evaluations. Draft, verify, trace.

---

## 2. Features

### 2.1 Sixteen document types, each with its own skeleton

Every type is a separate module containing structure templates, required-element checklists, common failure modes, and annotated examples.

| Category | Type | What it produces |
|---|---|---|
| Statutory | Notice | Matter, basis, compliance requirements, deadline |
| | Report | Progress, problems, next steps |
| | Request / Reply | One matter per request; point-by-point reply |
| | Circular / Briefing | Situation summary, typical-case analysis, requirements |
| | Meeting minutes | Agenda, decisions, responsibility assignment |
| Administrative | Speech | Salutation, situation, tasks, requirements, closing |
| | Work report / Summary | Quantified results, concrete problems, actionable plans |
| | Research report | Background and method, current state, problems, recommendations |
| | Work plan | Objectives, task breakdown, safeguards |
| | Experience material | Practices, results, lessons |
| | Rules and regulations | General provisions, specific provisions, supplementary provisions |
| | Appointment notice | Basis, decision, notes |
| | Letter / Open letter | Audience, cause, request |
| | Press release | Lead, body, background |
| | Reflection essay | Takeaways, application, next steps |
| | Theoretical article | Thesis, sub-arguments, reasoning, conclusion |

### 2.2 Style system: two libraries plus peer review

- **Six administrative styles** (`govdoc-styles` v6.9.0): solemn-concise, plain-narrative, reasoned-argumentative, mobilizing, field-research, policy-expository
- **Nine book-derived styles** (`shuji` v6.8.0): *Inside the System*, ledger style, *Benefits as the Basis*, *The Hustle of a Small Town*, county-cadre style, structural-reform style, and more
- **Multi-pen review**: write the same brief in three styles, compare, and combine strengths
- **Style learning**: import your organisation's past documents and distill a house style (`govdoc-style-learn`)

### 2.3 Editing and quality control

- **Five-part QC report**: factual accuracy, terminology compliance, structural completeness, language defects, risk flags
- **4,272 confusable word pairs**: 权力/权利, 截止/截至, 法制/法治, and similar traps
- Typo, punctuation, and terminology-consistency checks
- **Rewrite, not regenerate**: preserve information density and existing facts; cut redundancy, fix word order, adjust register

### 2.4 Typesetting and export

- **GB/T 9704 layout audit matrix, 45 items**: header block, body, and record block checked item by item
- Font, size, line spacing, margins, and page numbers generated to standard layout
- Export to `.docx` (`python-docx`) for direct entry into document workflows

### 2.5 Draft-from-draft

`govdoc-material`: give it an existing document (a summary, a report, a leader's speech), extract reusable facts and figures, and restructure them into a new document type. Built for the common case of "turn last year's summary into this year's report."

### 2.6 Private organisational corpus

`govdoc-corpus`: import your organisation's historical documents into a local corpus for style reference. **All processing stays local; classified material must not be imported.** Scope and redaction checks run before ingestion.

### 2.7 Workflow orchestration

`govdoc-workflow`: for multi-stage tasks such as project approval, budget requests, or technical and financial review, it first lists the required node documents, then generates each one, producing a complete package instead of a single document with missing attachments.

### 2.8 Document review

`article-review` (v6.8.1), two modes:

- **A — deep analysis**: decompose claims and evidence, identify logical gaps
- **B — fact checking**: atomic claim decomposition, evidence retrieval, source grading, conclusion comparison table

Internally, one lead plus five specialists keep factual checking separate from logical analysis, so no single role both finds errors and grades the work.

### 2.9 Retrieval and data hub

`qiushi-db` connects "what to write" with "what it is based on":

- **Three retrieval modes**: TF-IDF, BM25, and hybrid ranking (hybrid3, optionally with a vector semantic path)
- **Faceted drill-down**: filter by document type, issuing body, year, or source
- **Source traceback**: every result carries title, issuing body, date, and URL

---

## 3. Training corpus and knowledge sources

The writing rules, style models, and claim library were not invented. They were **trained and distilled** from authoritative theoretical journals and policy texts. This is the fundamental difference from ordinary document-writing prompts: a prompt gives you a template; this gives you judgment grown from tens of millions of characters.

| Corpus | Scale | Role in this project |
|---|---|---|
| *Qiushi* and *Red Flag Manuscripts* | **5,820 articles / 26.97M characters** | Style and argumentation-pattern distillation, claim and quotation extraction, terminology comparison |
| Leadership speeches and reports | 14,901 articles / 24.58M characters | Authoritative phrasing traceback, formulation verification |
| Policy and governance monographs | 11 books / 92 chapters / 3.04M characters | Governance logic and structural distillation (nine book styles) |
| State Council Gazette | 14,863 articles / 66.70M characters | Document skeletons, clause-style drafting, bundled retrieval |

**Distilled outputs**

- **31,315** claims, each traceable to its source text
- **31,315** quotable lines, classified as parallelism, call-to-action, antithesis, or assertion
- Structural templates for 16 document types, 6 administrative styles, 9 book styles
- 48 routing regression cases and 26 writing/retrieval evaluation tasks

**Why this matters**

The hard part of Chinese official writing is not vocabulary. It is whether a formulation is correct and whether the tone is appropriate. General-purpose models produce sentences that look right but miss the register. Trained on texts of this kind, the model absorbs the **syntax of authoritative phrasing, the layers of argumentation, and the boundaries of word choice**, which brings output closer to how government documents actually read.

**Boundary statement**

- The first three corpora above are **not distributed with this repository**; copyright remains with the original rights holders. The repository provides fetching tools only — see [EXTERNAL_CORPUS.md](EXTERNAL_CORPUS.md). Only administrative documents such as the State Council Gazette are bundled.
- This is a personal open-source project. It has **no affiliation, partnership, or endorsement** with the *Qiushi* editorial office, the *Red Flag Manuscripts* editorial office, or any government body. Journal names are mentioned solely to describe corpus provenance.
- "Training" here means **rule distillation and retrieval-index construction**. No foundation model was retrained or fine-tuned. If you are looking for "a fine-tuned official-document model," this is not that.

---

## 4. What makes it different

### 4.1 It has a corpus, not just model memory

Models invent document numbers and formulations; a corpus does not. The training corpora are described above. What ships for direct retrieval is **14,933 central-government public documents — 66.76M characters spanning 2000–2026, with 100% URL and issuing-body coverage** (details in Section 5).

When drafting "pursuant to … (Guobanfa [20XX] No. X)", look it up first.

### 4.2 Every citation goes back to source

Not "relevant materials were consulted," but a clickable `url`, an explicit `source`, and a precise `publish_date`. Citations must survive someone opening the link — that is the difference between official writing and self-media.

### 4.3 One entry point, thirty modules loaded on demand

The host panel shows a single "Gongwen Master" skill. The 30 internal modules stay unloaded until an intent matches, at which point the corresponding `SKILL.md` is read. It covers 16 document types, 9 styles, QC, typesetting, and review without exhausting the context window.

### 4.4 A routing hub, so you do not memorise commands

`SKILL.md` defines six routing rule groups (document type, style, citation, novice, action, team mode) plus a semantic fallback. "Help me put something together" is understood. "Write a report for the director, with data" routes to retrieval first, then drafting.

The rule layer is guarded by **48 regression cases**, so rule changes cannot silently break routing.

### 4.5 Self-checking and evaluable, not a black box

- `verify_install.py`: **20** installation checks (module integrity, data assets, dependencies, version consistency, frontmatter compliance)
- `datahub/eval/`: **26** writing and retrieval evaluation tasks with judge scripts
- `rules_regression.py`: **48** routing regression cases

You know immediately whether a change caused a regression.

### 4.6 Code and data under separate licences, with boundaries in writing

Code is Apache-2.0. Bundled data contains only **administrative documents** (State Council Gazette and similar), which are not subject to copyright under Article 5 of China's Copyright Law. Journals, books, and local statistics are never bundled; fetching tools are provided instead.

The point is not disclaiming liability, but making it clear to downstream users what can and cannot be redistributed. See [DATA_LICENSE.md](DATA_LICENSE.md).

### 4.7 Local-first

No network access by default except for explicit fetch commands. Retrieval, drafting, QC, and typesetting all run locally; the corpus never leaves the machine.

---

## 5. Data foundation

`datahub/sqlite/gongwen_corpus.db.gz` — 57 MB compressed, 200 MB extracted.

**Sources**

| Source | Documents | Nature |
|---|---|---|
| State Council Gazette | 14,863 | Administrative documents published by the State Council, its General Office, and ministries |
| National laws and regulations database | 50 | Statutory texts |
| Central ministry policies | 20 | Normative documents |

**Document types (top 8)**

| Type | Count | Type | Count |
|---|---|---|---|
| Rules and regulations | 5,898 | Replies | 960 |
| Notices | 2,417 | Decisions | 611 |
| Opinions | 1,940 | Administrative regulations | 548 |
| Other | 1,309 | Appointments | 448 |

Remaining: orders 328, announcements 298, government work reports 38, circulars 31, reports 23, New Year messages 14, miscellaneous 70.

**Schema**

```
articles                          Main table (14,933 rows)
├── id / title / author           Title, issuing body
├── source / data_source          Source and collection channel
├── publish_date / issue_year     Publication date, year
├── url                           Source URL (per-row traceability)
├── content                       Full text
├── genre                         Document type (15 classes, 100% filled)
├── word_count / crawl_time       Length, collection time
└── keywords / topic / level      Extended labels (partially filled)

articles_fts                      FTS5 full-text index (unicode61 tokenizer)
meta                              Build metadata
```

**Example queries**

```sql
-- How a document type evolved over the years
SELECT publish_date, title FROM articles
WHERE genre='通知' AND publish_date LIKE '2015%' LIMIT 5;

-- Authoritative source of a formulation
SELECT title, author, url FROM articles
WHERE content LIKE '%新质生产力%' LIMIT 10;

-- Count by issuing body
SELECT author, COUNT(*) FROM articles GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
```

**Known limitations**: 50 statutory entries contain only a title, no body text; 640 entries are shorter than 200 characters (mostly appointment and reply notices) and should be avoided as long-form references. The remaining 12,081 exceed 1,000 characters.

Questions about schema design, collection methodology, retrieval implementation, or corpus governance are welcome by email (see Section 12).

**Theoretical journal corpus**: the repository does not contain *Qiushi*, *Red Flag Manuscripts*, or book texts. Fetch them yourself with the bundled tools:

```bash
python tools/fetch_corpus.py --plan      # preview issues to be fetched
python tools/fetch_corpus.py --journal   # fetch into your local database
```

Fetched content stays in your local database for personal study and research. See [EXTERNAL_CORPUS.md](EXTERNAL_CORPUS.md).

---

## 6. Quick start

```bash
# 1. Place in your skills directory
cp -r gongwen-master ~/.workbuddy/skills/
#   Claude:  ~/.claude/skills/      Generic:  ~/.skills/

# 2. Extract the bundled data (~200 MB)
python tools/unpack_data.py

# 3. Install dependencies
pip install -r requirements.txt

# 4. Build indexes (required on first run)
python tools/build_fts.py                            # full-text index, ~15 s
python datahub/scripts/qs/qiushi_engine.py reindex   # semantic index, ~1-3 min

# 5. Self-check
python verify_install.py
```

> Step 4 can be skipped, but the first search will build the index on the fly. It produces no output for several minutes and looks like a hang. For a quick trial, set `GONGWEN_FAST=1` to use the full-text fast path.

---

## 7. Usage

No commands to memorise. Just say what you need:

| You say | It does |
|---|---|
| Write a notice about flood-control inspections | Selects the notice type, applies structure, drafts |
| Draft the director's speech for the project meeting | Speech skeleton, mobilising style, parallel structures |
| Write a work report with supporting data | Report structure, retrieves and cites source texts |
| Turn last year's summary into this year's report | Draft-from-draft: extract facts, update framing, restructure |
| This paragraph is loose, tighten it | Rewrite: keep density, cut redundancy |
| Quality-check this document | Five-part report: facts, terminology, structure, language, risk |
| Write the industry analysis in *Inside the System* style | Switches to that book's style |
| Fact-check the figures in this article | Fact-checking mode: claim-by-claim evidence and grading |
| What documents does a project approval need? | Workflow orchestration: node list, then each document |
| Let's write this together, one version each | Enables the expert team for competing drafts |

---

## 8. How it works

```
Keyword routing (document type / style / citation / novice / action)
        ↓
Semantic routing fallback (vector match for colloquial requests)
        ↓
Load the matching module's writing rules (on demand, not all at once)
        ↓
Query the data foundation, retrieve source text and provenance
        ↓
Draft → optional QC → optional typesetting and export
```

Routing rules live in `SKILL.md`; modules live in `references/`, loaded only when selected. Team mode (multi-role drafting) requires an explicit request and adds no overhead to ordinary drafting.

---

## 9. Repository layout

```
gongwen-master/
├── SKILL.md                 Entry point: routing rules and writing flow
├── registry.json            Module registry (26 governed skills)
├── references/
│   ├── govdoc-*/            16 document types + editing / typesetting / drafting / corpus / workflow
│   ├── govdoc-styles/       Six administrative styles + peer review
│   ├── shuji/               Nine book-derived styles
│   ├── article-review/      Deep analysis + fact checking
│   └── qiushi-db/           Retrieval data hub
├── datahub/
│   ├── sqlite/              Bundled database (.gz)
│   ├── scripts/             Retrieval, crawling, index rebuild
│   ├── schema/              Table definitions and DDL
│   └── eval/                Evaluation tasks and judges
├── agents/                  Twelve expert-team role definitions
├── tools/                   Unpack, index build, corpus fetch
└── verify_install.py        Installation self-check (20 items)
```

---

## 10. Data boundaries

| Tier | Content | Bundled |
|---|---|---|
| A | State Council Gazette, laws, ministry policies | Yes; Apache-2.0 covers the code, no rights claimed over the data |
| B | Journal articles, news reports, book texts | No; fetch separately |
| C | Local statistical data | No; removed entirely |

Full licensing detail in [DATA_LICENSE.md](DATA_LICENSE.md); third-party components in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

> Classified material, work secrets, and personal data must not be processed with this tool.

---

## 11. License

Code, documentation, and skill definitions are licensed under the [Apache License 2.0](LICENSE), copyright Gongwen Master Contributors.

Bundled data consists of publicly released administrative documents. This project claims no copyright over them and retains original sources and links. Bug reports and feature requests are welcome by email; pull requests adding document types or style samples are welcome too.

---

## 12. Contact

**All enquiries by email: waster9001@gmail.com**

| Purpose | Channel |
|---|---|
| Bug reports, feature requests | **waster9001@gmail.com** |
| **Database technical discussion** (data sources, schema design, retrieval implementation, corpus governance) | **waster9001@gmail.com** |
| Licensing, collaboration, rights-holder notices | **waster9001@gmail.com** |

On the bundled database, the following topics are welcome: collection and cleaning standards for gazette corpora, field design for the `articles` table, trade-offs between FTS5 and BM25/TF-IDF hybrid retrieval, deduplication and provenance tracking, and how to merge new corpora into the existing schema. Please describe your context and the problem you are trying to solve; I reply where I can.

Rights-holder notices are verified and acted on within 72 hours.
