# Sources behind this skill

Reviewed Nov 2026. Each row records what the source actually argued, whether it
applies to Project Sunday, and where the rule landed in the codebase. Kept so
that a future reader can tell an evidence-based rule from an opinion.

| Source | What it claimed | Applies here? | Landed as |
|---|---|---|---|
| Instagram — "Everything Claude Code" (aimortal.ig, DfX7jvSSE4W) | A 64-agent / 261-skill / 84-command bundle turns one coding agent into a team; installs in one command | Partly. The *packaging* idea (skills + hooks + memory as versioned project files) is sound. The agent-count is not a goal. | This skill's file layout; `apps/web/.agents/skills/` already used the same convention |
| Instagram — "Everything Claude Code" (real_bruno_souza, DfnPGs5h2gb) | Same bundle, 68 agents / 292 skills / 94 commands, hooks, memory, security scanning, 1,282 tests | Partly. "Backed by tests" is the part worth copying, not the catalogue. | `tests/test_agent_loop.py` as the loop's verification; §2 |
| Instagram — "second agent checks your agent, auto-compact, 690 hours straight" (j.t.rivard, DfS0h0Nqyi4) | Run a verifier agent over the worker's work; auto-compaction keeps long runs coherent; an agent ran 690h unattended | No to the second model call — it halves a 250/day budget. Yes to observable long runs. | §2 (deterministic verification), §5 (supervision, watchdog) |
| Instagram — Cloudflare/Anthropic "Code Mode" (pragmaticcoder.ai, De6pmMnBu2x) | Every MCP tool manual loads before the agent acts (5 apps ≈ 55k tokens); 2,500 endpoints would be 1.17M tokens; let the AI write one script and return only the answer | Diagnosis yes, cure no. Script execution defeats per-name approval tiers. | §1 — tool declarations priced per request; Code Mode explicitly rejected with the reason |
| Instagram — plugin roundup (ai_wealth_codes, Dem6or1zHGr) | OmniRoute (model routing), ClaudeMem (cross-session memory), Headroom (context trimming), ClaudeCodeSetup, TaskObserver | The four mechanisms, yes; none of the products. | §3 (curated memory), §4 (routing), `agent_turns` as the observer |
| Instagram — "6 legal traps in vibe-coded apps" (adilet.fndr, DdyqycEINNe) | Age gate, self-hosted fonts, session-replay consent + input masking, unsubscribe link + postal address, renewal terms beside the subscribe button, DMCA agent — penalties per visitor/session/email | Mostly no: `apps/web` has no billing, no marketing email, no session replay, no age-restricted content. Retained as a gate on future additions. | Appendix below |
| Instagram — model compression (rahuliyer.ai, DelT0XMRFvW) | A large model compressed to ~7.9 GB, "96%" of original quality | No. Reported figures are benchmark-specific and the free tier is gated on requests, not tokens. | §6 |
| YouTube — "Get Unlimited Claude Code on Your Own Computer" (Sharbel A., l-FG6S-5aPY) | Separate the brain from the app; route the app at free/large hosted models (NVIDIA 550B, OpenRouter free tier, OmniRoute); paid DeepSeek via Magpie | The brain/app split, yes — that is already `route_turn` vs the worker. The provider shopping, no. | §4 — cascade order and "don't add a provider to fix quality" |
| YouTube — BytePlus Coding Plan (ExYaYXPiFPo) | One multi-model subscription with "intelligent auto-routing" picks the model per task | No for the product; the auto-route idea is already `pick_model`. | §4 |
| YouTube — "Free AI tools for 2027" (warikoo careers, hG-oQv6BHJk) | "AI tool is not important — the problem you solve is." Two principles before using AI: solve a real problem, don't collect tools | Yes, directly. | §7 |
| GitHub — FareedKhan-dev/kimi-k3-in-c | 2.78T-parameter MoE, single CPU, 8.24 GB RAM, portable C99, no BLAS/framework/GPU | No. No weights run in this project. The transferable shape (small hot path, page the rest) is already the loader + cold archive. | §6 |
| Instagram — age-restricted post (erynbuilds, De84o3WhStP) | Not retrievable — Instagram gated the content | Not assessed. | — |

## Appendix — legal/compliance gate for `apps/web`

Not action items today. Each becomes required at the moment the trigger on the
right happens, and the cost of missing one is per-visitor, not per-incident.

| Trigger | Then |
|---|---|
| Any paid plan added | Price, renewal period and terms beside the subscribe button; cancellation path before payment details |
| Any marketing email added | Unsubscribe link and a postal address in every send; `gmail_send` stays `hold` regardless |
| Any analytics or session replay added | Consent gate and input masking before the first event; self-host the script |
| Any font added from a CDN | Self-host it — a Google Fonts `<link>` is a third-party request carrying the user's IP |
| Publishing to a wider audience | Age gate if content warrants it; DMCA agent registration |
| Any user-generated content | Takedown procedure, not just a terms page |
