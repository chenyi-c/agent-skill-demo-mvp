# Research Skill Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing Agent demo into a testable research-skill laboratory with multi-turn clarification and constrained academic search.

**Architecture:** Add a small in-memory research-session store and two BaseSkill adapters. The frontend discovers Skills from the API and preserves a browser session ID. The search adapter invokes the upstream `paper-search` CLI with a fixed source allowlist and returns structured partial-failure results.

**Tech Stack:** FastAPI, Pydantic, httpx/subprocess, pytest, vanilla JavaScript, paper-search-mcp CLI.

---

### Task 1: Research clarification state machine

**Files:**
- Create: `app/services/skills/research_clarification.py`
- Modify: `tests/test_skills.py`

- [ ] Write failing async tests for creating a session, asking only for the next missing field, and producing a brief after five fields are supplied.
- [ ] Run `python -m pytest tests/test_skills.py -q` and confirm the tests fail because the research Skill does not exist.
- [ ] Implement `ResearchClarificationSkill` with `session_id`, a five-field state dictionary, deterministic question options, and `research_brief` output after completion.
- [ ] Run `python -m pytest tests/test_skills.py -q` and confirm all Skill tests pass.

### Task 2: Constrained academic-search adapter

**Files:**
- Create: `app/services/skills/academic_search.py`
- Modify: `tests/test_skills.py`, `requirements.txt`

- [ ] Write failing tests that assert the adapter only supplies `arxiv,semantic,openalex,crossref`, clamps the result count to five, parses JSON, and reports a missing CLI without fabricating papers.
- [ ] Run the targeted tests and confirm failure because the adapter does not exist.
- [ ] Implement `AcademicSearchSkill` using a command runner dependency, structured source status, and a `paper-search` command invocation; add the upstream package dependency.
- [ ] Run the targeted tests and confirm they pass without network calls.

### Task 3: Generic API and routing contract

**Files:**
- Modify: `app/models/chat.py`, `app/services/agent.py`, `app/services/skills/__init__.py`, `app/api/routes.py`
- Modify: `tests/test_api.py`

- [ ] Write failing API tests for session propagation, rule routing of research and literature requests, and generic manual Skill validation.
- [ ] Run `python -m pytest tests/test_api.py -q` and confirm expected failures.
- [ ] Add `session_id` to request/response models, register the two Skills, add keyword routing, and pass generic fields through only when their schemas accept them.
- [ ] Restrict runtime model configuration to supported HTTPS hosts, preserve an existing Key when the browser sends a mask, and return an explicit configuration error instead of silently hiding it.
- [ ] Run API tests and then `python -m pytest -q`.

### Task 4: Dynamic, safe research-skill UI

**Files:**
- Modify: `static/index.html`
- Modify: `tests/test_api.py`

- [ ] Write an API test confirming both research Skills are advertised with their schemas.
- [ ] Run it to confirm the new Skills are not yet registered.
- [ ] Build the select options from `/api/skills`, retain a browser session ID, use a relative API URL, and escape all dynamic trace fields before inserting them into the DOM.
- [ ] Run `python -m pytest -q` and perform a local HTTP smoke check of `/`, `/api/skills`, and both research API calls.

### Task 5: Versioning and delivery

**Files:**
- Modify: `.gitignore`, `README.md`
- Create: `skills/research-clarification/SKILL.md`, `skills/constrained-literature-search/SKILL.md`

- [ ] Update README with the research-lab flow, paper-search-mcp installation, source allowlist, and test command.
- [ ] Stop ignoring the two reusable Skill folders so the GitHub repository contains the experiment assets.
- [ ] Run `git diff --check`, `python -m pytest -q`, and live smoke tests; inspect the staged diff; commit and push `codex/research-skill-lab` to origin.
