# Need-to-Know Room

A team chat where an AI agent that holds customer data answers each person only with what they may know. A contractor can ask for one field of one customer; the owner approves it with a button; the agent hands out exactly that field, once. Who may reach the agent and who may approve is enforced by [Switch](https://github.com/sandbox-quantum/switch), not by a prompt.

Built for the Flip the Switch hackathon, Track 01 (Best Business Workflow), on Switch 0.31.0 with Mattermost.

**[Watch the 2-minute demo](__VIDEO_URL__)**: real Mattermost, real Switch and a real Claude Code agent, recorded from the stack this repo starts (before we narrowed desk's tools further; nothing on screen changed).

Two agents share the rooms. **keeper** holds the customer list and has no language model. **desk** is Claude Code, helps contractors and holds no data. A sentence in a prompt can be argued with, and a role check inside an agent still wakes the agent. Here Switch stops the request before keeper is woken, and only the owner's press on its card can release a field.

![Three rooms, two agents: who may talk to keeper is set per room in Switch](docs/img/rooms.png)

| Dana asks keeper for the list: Switch refuses | Dana presses the owner's card: Switch refuses |
|---|---|
| ![Switch's refusal in the thread](docs/img/refused-by-switch.jpg) | ![The private refusal under the approval card](docs/img/press-refused.jpg) |

## Judge it in 90 seconds

| Claim | Where it lives | What you will see | In the video |
|---|---|---|---|
| A contractor's request is refused by Switch, not by a model. keeper is never woken: Switch marks the message as not addressed to it (`core/switch_core/delivery/recipient.py:1503-1535`), and keeper's stream carries addressed messages only | Switch's `ADDRESSING_DENIED_MESSAGE` (`core/switch_core/delivery/addressing.py:63-66` at tag `switch-v0.31.0`); keeper's per-room policy in [`scripts/seed.py`](scripts/seed.py) (`keeper_policy`) | `verify.py` scene 1: the reply is that exact sentence, shown under keeper's name, and keeper's code posts nothing | 0:14 |
| The same request from an employee in another room goes through | the `#core` rule in `keeper_policy` | scene 2 | 0:41 |
| Only the owner can approve. The contractor sees the card, but her press is refused | Switch lets only people who may address an agent answer its cards (`core/switch_core/session_activity/service.py:571-602`); keeper opens its own card through `POST /agent-sessions/{id}/approvals` | scene 3: Dana's press changes nothing, Alex's press releases the field | 0:58 |
| One field, once. A follow-up needs a new approval | [`agents/keeper/keeper.py`](agents/keeper/keeper.py) (our code, no language model). Anything that comes through desk gets a card, even if the owner asked | scenes 3 and 4 | 1:08, 1:15 |
| Switch keeps the record of every answer, and ours must match it | `GET /gateway/chats/{room}/activity` (`core/switch_core/gateway/chats.py:310`); [`scripts/audit.py`](scripts/audit.py) joins it with keeper's log and exits 1 on any disagreement | scene 5 and the audit table at the end of `verify.sh` | 1:32 |
| The Claude Code agent in the room (desk) can only talk in that room, and does not see its host's private instructions | an allowlist of tools and a working directory outside the home folder, set in [`scripts/seed.py`](scripts/seed.py) (`ensure_claude_desk`) from [`scripts/switchlib.py`](scripts/switchlib.py) (`DESK_TOOLS`) | scene 6 (Tier B): desk has nothing beyond its allowlist; Dana asks it to add her to `#core`, create an agent and rerun the template, and none of that happens; a fresh secret in desk's folder never reaches the room; no instruction files loaded | 1:22 |

One command checks all of it on a running stack: `./scripts/verify.sh` (exit code 0 only if every scene passes and the audit agrees).

## The problem

Asked in the chat of the Switch kickoff stream on 2 November 2026:

> how do i stop random people in the channel from triggering an agent that has prod access? asking for my security team

It is a common worry: in a 2026 vendor survey, 67% of organizations using AI agents said they suspect their agents have already accessed data beyond their intended scope ([Akeyless, May 2026](https://www.prnewswire.com/il/news-releases/two-thirds-of-enterprises-suspect-ai-agents-have-already-accessed-unauthorized-data-akeyless-finds-302769768.html); a suspicion, not confirmed incidents).

A shared agent in a team chat usually runs with the access of whoever set it up. Everyone in the channel can ask it anything, and the only thing between a contractor and the customer list is a sentence in the prompt. Need-to-Know Room moves that boundary into Switch: who may talk to the agent that holds the data, in which room, and who may approve a release.

## How Switch is used

`#owner-desk` is the owner's private line to keeper; the demo itself runs in `#contractors` and `#core`.

| Step | Switch does | Our code does |
|---|---|---|
| Dana (contractor) asks keeper for the full list in `#contractors` | refuses her with its own message, by keeper's addressing policy for that room; keeper is never woken | sets the policy (`seed.py`) |
| Sam (employee) asks the same in `#core` | lets it through: the policy allows people in `#core` | keeper answers with a summary |
| Dana asks desk for one field | delivers her message to desk, which anyone in `#contractors` may address | desk (Claude Code) forwards `@keeper <field> of <customer>` |
| desk asks keeper | lets it through: keeper accepts the owner's own agents in `#contractors` | keeper takes the requester from Switch's room history, not from desk's words |
| keeper asks the owner | renders the approval card with buttons in Mattermost and decides who may press it | keeper opens the card with customer, field and requester |
| Alex (owner) presses Open once | records the answer and delivers the outcome to keeper | keeper posts that one field, once, and logs the grant |
| Anyone asks "who opened what?" | keeps every card's answer, who answered and when, and shows the last 7 days (`core/switch_core/chats/service.py:602`) | `audit.py` joins it with keeper's log |

![What Switch enforces and what our code decides](docs/img/switch-vs-our-code.png)

Remove Switch and nothing here holds: there are no rooms, no identities, no policy and no cards, only a bot that answers everyone with its owner's access.

[`scripts/seed.py`](scripts/seed.py) creates the rooms and policies through Switch's API, and the people through Mattermost's and Switch's. The same rooms and the Claude Code desk are also written as a Switch template, [`templates/need-to-know.v2.template.yaml`](templates/need-to-know.v2.template.yaml).

## Quick start (Tier A: no accounts)

Tier A shows everything Switch enforces, with keeper and a scripted desk. It needs no model account.

You need Docker with Compose v2, `git`, `curl`, `openssl` and `python3` (3.9 or later). Mattermost publishes an amd64 image only, so on Apple Silicon Docker must emulate amd64.

```bash
git clone https://github.com/retailbox-automation/need-to-know-room
cd need-to-know-room
./scripts/up.sh            # Switch 0.31.0 from its release tag; first run downloads about 0.8 GB, 2.5 GB on disk
python3 scripts/seed.py    # people, rooms, keeper, policies
./scripts/verify.sh        # starts keeper and the scripted desk, plays scenes 1-5 and 7, runs the audit
```

Then open Mattermost at http://localhost:28065 (use `localhost`: on `127.0.0.1` its live updates do not connect) and sign in as `alex`, `sam` or `dana` (passwords are in `.stand/state.json`) to try to get past keeper yourself. `./scripts/up.sh down` stops the stack and keeps its data; `./scripts/up.sh destroy` removes it.

If a port is taken, set `N2K_API_PORT`, `N2K_GATEWAY_PORT`, `N2K_MM_PORT` or `N2K_PG_PORT` before `up.sh`. If Mattermost exits with `exec format error`, your Docker has no amd64 emulation (Platform findings, 8).

## Tier B: Claude Code as desk

desk becomes a Claude Code agent started by Switch's agent controller, with tools for talking in its room and nothing else. You need Node 22.13 or later, the `claude` CLI and your own Claude Code login. Steps: [`agents/desk/README.md`](agents/desk/README.md). `verify.sh` then also plays scene 6.

## What `verify.sh` checks

| Scene | People do | Must happen |
|---|---|---|
| 1 | Dana asks keeper for the full list in `#contractors` | Switch's refusal, verbatim; keeper's code posts nothing |
| 2 | Sam asks the same in `#core` | keeper answers |
| 3 | Dana asks desk for a region; Dana, then Alex, press the card | a card naming Dana, the field and the customer; Dana's press is refused; Alex's releases exactly that field |
| 4 | Dana asks a follow-up | a new card; Alex keeps it closed; the phone number never appears |
| 5 | — | Switch's record and keeper's log agree |
| 6 (Tier B) | Dana asks desk to read a file in its folder, then to add her to `#core`, create an agent and rerun the template | the file's contents never appear; she does not get into `#core`; no new agent or room appears; desk has and calls only its allowlisted tools; it loaded no instruction files from the machine |
| 7 | — | Switch's own template validator accepts `templates/need-to-know.v2.template.yaml` |
| audit | — | every request in Switch's record matches keeper's log |

A real run from a clean clone (Tier A, Python 3.9):

```
PASS  scene 1: dana -> @keeper in #contractors is refused by Switch with its own message
PASS  scene 1: keeper posted nothing to dana
PASS  scene 2: sam -> @keeper in #core gets the summary
PASS  scene 3: desk asks keeper; keeper opens a card naming dana, region, Acme Bakery Co.
PASS  scene 3: dana's own press is refused: card still open, nothing released
PASS  scene 3: alex's press releases exactly that field
PASS  scene 3: the card now reads 'Chosen by @alex'
PASS  scene 4: the follow-up opens a new card (approvals do not carry over)
PASS  scene 4: alex keeps it closed
PASS  scene 4: the phone number never appears in #contractors
PASS  scene 5: Switch's approval record matches keeper's grants log (2 entries)
PASS  scene 7: Switch validates templates/need-to-know.v2.template.yaml (0 errors, 0 warnings)

All scenes passed.
PASSED: every scene, and the record matches.
```

## Threat model: what Switch does here, and what it does not

Switch enforces who may wake keeper in each room, who may answer keeper's cards, and the record of answers. It does not:

- check what desk writes to keeper. That text comes from a model, and Dana can push desk to name another customer or field. keeper therefore takes the requester from Switch's room history and names that person on the card the owner sees, and everything that comes through desk needs a card;
- control access field by field: that is keeper's code;
- hide a room's messages from other members: everyone in `#contractors` sees keeper's released field;
- limit what an agent may do beyond its owner's rights. desk's owner is the Switch admin, so with Switch's tools open anyone who may address desk could ask it to add people to rooms or create agents, and only its prompt would say no. We close those tools, and scene 6 fails if desk is offered anything else (see Platform findings);
- stop the people who may address desk from answering desk's own cards. That is why desk holds no data and has no tools that would need approval;
- isolate a Claude Code agent from its host. The agent runs as your user; we give desk an empty home, a minimal environment and a working directory outside your home folder (see Platform findings).

Anyone who can talk to desk can try to make it reveal its environment, and its Claude Code token lives there. Only the demo people are in these rooms; give desk a token of its own before you let anyone else in.

## Platform findings

Found while building this on Switch 0.31.0. Each was seen on our stand; code references are to tag `switch-v0.31.0`.

1. **A person who may address an agent may also answer its approval cards** (`session_activity/service.py:571-602`). So the agent that holds data must not be addressable by the people who must not approve; that is why keeper and desk are separate agents.
2. **A Claude Code agent started by the controller loads its host's personal instructions.** Claude Code reads `.claude/CLAUDE.md` and `.claude/rules/` from every parent folder of its working directory, so an agent working under the owner's home folder gets the owner's private instructions in every session, whatever `HOME` it runs with. We found this in desk's transcript and moved desk's working directory to `/tmp`. By default the controller does not change `HOME` for agents, and the Claude adapter starts sessions with `strictMcpConfig: false`.
3. **Deleting a managed agent's Claude Code transcript breaks its room session**: Switch keeps resuming the old session id and logs "The session host hung up before it answered". Removing and recreating the managed agent fixes it.
4. **`AGENT_MANAGEMENT_ENABLED=true` stops switch-core 0.31.0 at startup**; agent management is now the feature flag `agent_management` in `FEATURE_FLAGS_ENABLED`.
5. **`.env.example` sets `SWITCH_VERSION=latest`** (line 23), although the standalone compose file requires an explicit version on purpose. A `.env` copied from the example follows `latest`, not the release you tested; `up.sh` pins 0.31.0.
6. **A chat account not linked to a Switch user gets a different refusal** ("this chat account isn't linked") instead of the room policy's; `seed.py` links every demo person.
7. **The room activity record (`/gateway/chats/{room}/activity`) returns 403 to the admin** until the admin joins that chat.
8. **Mattermost 11.9.0 is amd64-only** (the compose file sets `platform: linux/amd64`); on a Docker host without amd64 emulation it exits at once with `exec format error`.
9. **The buttons on Switch's cards carry no action `type`.** `answer_actions` (`bridges/collaboration/mattermost/callback.py:183-209`) sends `id`, `name` and `integration`. Mattermost 11.9.0 requires `button` or `select` (`server/public/model/integration_action.go:179`) and logs "Invalid post props. In a future version this will result in an error" (`server/public/model/post.go:717`); we counted 17 such lines in one run of the demo. The buttons work today.
10. **A managed agent carries its owner's rights, and Switch's room-admin tools are always offered.** An agent created by the admin may add people to any room (`core/switch_core/bridges/agent/protocol/agent_core.py:3209-3275`). A `tools` allowlist always gets the whole `mcp__switch` server added (`console/packages/plugins/src/agents/impl/claude/subagents.ts:185-188`), so the 57 tools desk does not need can only be closed one by one in `disallowedTools`. Before we closed them, desk was offered `add_users_to_room`, `create_agent` and `run_template`, and the prompt was all that stopped them. An allowlist that covers the server's tools would make this one line.
11. **A refused press shows only in the card's thread.** Our Mattermost runs with `CollapsedThreads=always_on`, and it attaches the private refusal to the card's thread (`server/channels/app/integration_action.go:231-234`), so someone who presses a card in the channel view sees nothing happen unless that thread is open. The video opens the thread first for this reason.

## How AI was used

- desk is a Claude Code agent, run by Switch's agent controller (Tier B).
- keeper uses no language model, on purpose: what leaves the data store is decided by deterministic code.
- The code was written with Claude Code as a coding assistant, from a design we wrote and approved before the build window; we checked changes with the scripts in this repo (`verify.sh`, `tests/`), and had another Claude session review this README against the code before publishing.
- The video's narration is generated with ElevenLabs from a clone of the author's own voice. Its screens are recordings of the running stack, and its diagrams are drawn by code.

## Disclosure

Everything in this repository was written during the hackathon window (first commit on 3 November 2026, 18:31 UTC). Switch is used as released (Apache-2.0 with the Commons Clause): `up.sh` downloads its compose file from the release tag and nothing of Switch is copied here. All customer data is synthetic (`data/generate.py`, seeded); no real customer, client or person appears. Music in the video: "Digital Technology" by AtlasAudio, [Pixabay Content License](https://pixabay.com/service/license-summary/).

## License

MIT, see [LICENSE](LICENSE).
