# Need-to-Know Room

A team chat where an AI agent that holds customer data answers each person only with what they may know. A contractor can ask for one field of one customer; the owner approves it with a button; the agent hands out exactly that field, once. The rules are enforced by [Switch](https://github.com/sandbox-quantum/switch), not by a prompt.

Built for the Flip the Switch hackathon, Track 01 (Best Business Workflow), on Switch 0.31.0 with Mattermost.

## Judge it in 90 seconds

| Claim | Where it lives | What you will see |
|---|---|---|
| A contractor's request is refused by Switch, not by a model. keeper never receives it. | Switch's `ADDRESSING_DENIED_MESSAGE` (`core/switch_core/delivery/addressing.py:63-66` at tag `switch-v0.31.0`); keeper's per-room policy in [`scripts/seed.py`](scripts/seed.py) (`keeper_policy`) | `verify.py` scene 1: the reply is that exact sentence, and keeper posts nothing |
| The same request from an employee in another room goes through | the `#core` rule in `keeper_policy` | scene 2 |
| Only the owner can approve. The contractor sees the card, but her press is refused | Switch lets only people who may address an agent answer its cards (`session_activity/service.py:571-602`); keeper opens its own card through `POST /agent-sessions/{id}/approvals` | scene 3: Dana's press changes nothing, Alex's press releases the field |
| One field, once. A follow-up needs a new approval | [`agents/keeper/keeper.py`](agents/keeper/keeper.py) (our code, no language model) | scenes 3 and 4 |
| Switch keeps the record of every answer, and ours must match it | `GET /gateway/chats/{room}/activity` (`gateway/chats.py:310`); [`scripts/audit.py`](scripts/audit.py) joins it with keeper's log and exits 1 on any disagreement | scene 5 and the audit table at the end of `verify.sh` |
| The Claude Code agent in the room (desk) cannot read files and does not see its host's private instructions | `disallowedTools` and a working directory outside the home folder, set in [`scripts/seed.py`](scripts/seed.py) (`ensure_claude_desk`) | scene 6 (Tier B): a fresh secret in desk's folder never reaches the room; desk's transcript shows no instruction files loaded |

One command checks all of it on a running stack: `./scripts/verify.sh` (exit code 0 only if every scene passes and the audit agrees).

## The problem

Asked in the chat of the Switch kickoff stream on 2 November 2026:

> how do i stop random people in the channel from triggering an agent that has prod access? asking for my security team

A shared agent in a team chat usually runs with the access of whoever set it up. Everyone in the channel can ask it anything, and the only thing between a contractor and the customer list is a sentence in the prompt. Need-to-Know Room moves that boundary into Switch: who may talk to the agent that holds the data, in which room, and who may approve a release.

## How Switch is used

| Step | Switch does | Our code does |
|---|---|---|
| Dana (contractor) asks keeper for the full list in `#contractors` | refuses her with its own message, by keeper's addressing policy for that room; keeper is never woken | sets the policy (`seed.py`) |
| Sam (employee) asks the same in `#core` | lets it through: the policy allows people in `#core` | keeper answers with a summary |
| Dana asks desk for one field | delivers her message to desk, which anyone in `#contractors` may address | desk (Claude Code) forwards `@keeper <field> of <customer>` |
| desk asks keeper | lets it through: keeper accepts the owner's own agents in `#contractors` | keeper takes the requester from Switch's room history, not from desk's words |
| keeper asks the owner | renders the approval card with buttons in Mattermost and decides who may press it | keeper opens the card with customer, field and requester |
| Alex (owner) presses Open once | records the answer and delivers the outcome to keeper | keeper posts that one field, once, and logs the grant |
| Anyone asks "who opened what?" | keeps every card's answer, who answered and when, for 7 days (`session_activity/maintenance.py:28`) | `audit.py` joins it with keeper's log |

Remove Switch and nothing here holds: there are no rooms, no identities, no policy and no cards, only a bot that answers everyone with its owner's access.

The rooms, people and policies are created through Switch's API by [`scripts/seed.py`](scripts/seed.py). The same rooms and the Claude Code desk are also written as a Switch template, [`templates/need-to-know.v2.template.yaml`](templates/need-to-know.v2.template.yaml).

## Quick start (Tier A: no accounts)

Tier A shows everything Switch enforces, with keeper and a scripted desk. It needs no model account.

You need Docker with Compose v2, `git`, `curl`, `openssl` and `python3` (3.9 or later). Mattermost publishes an amd64 image only, so on Apple Silicon Docker must emulate amd64.

```bash
git clone https://github.com/retailbox-automation/need-to-know-room
cd need-to-know-room
./scripts/up.sh            # Switch 0.31.0 from its release tag; first run pulls about 2.5 GB
python3 scripts/seed.py    # people, rooms, keeper, policies
./scripts/verify.sh        # starts keeper and the scripted desk, plays scenes 1-5, runs the audit
```

Then open Mattermost at http://127.0.0.1:28065 and sign in as `alex`, `sam` or `dana` (passwords are in `.stand/state.json`) to try to get past keeper yourself. `./scripts/up.sh down` stops the stack and keeps its data; `./scripts/up.sh destroy` removes it.

## Tier B: Claude Code as desk

desk becomes a Claude Code agent started by Switch's agent controller, without file, shell or web tools. You need Node 22.13 or later, the `claude` CLI and your own Claude Code login. Steps: [`agents/desk/README.md`](agents/desk/README.md). `verify.sh` then also plays scene 6.

## What `verify.sh` checks

| Scene | People do | Must happen |
|---|---|---|
| 1 | Dana asks keeper for the full list in `#contractors` | Switch's refusal, verbatim; keeper posts nothing |
| 2 | Sam asks the same in `#core` | keeper answers |
| 3 | Dana asks desk for a region; Dana, then Alex, press the card | a card naming Dana, the field and the customer; Dana's press is refused; Alex's releases exactly that field |
| 4 | Dana asks a follow-up | a new card; Alex keeps it closed; the phone number never appears |
| 5 | — | Switch's record and keeper's log agree |
| 6 (Tier B) | Dana asks desk to read a file in its folder | desk answers, the file's contents never appear, and desk loaded no instruction files from the machine |
| audit | — | every request in Switch's record matches keeper's log |

## Threat model: what Switch does here, and what it does not

Switch enforces who may wake keeper in each room, who may answer keeper's cards, and the record of answers. It does not:

- check what desk writes to keeper. That text comes from a model, and Dana can push desk to name another customer or field. keeper therefore takes the requester from Switch's room history and names that person on the card the owner sees;
- control access field by field: that is keeper's code;
- hide a room's messages from other members: everyone in `#contractors` sees keeper's released field;
- stop the people who may address desk from answering desk's own cards. That is why desk holds no data and has no tools that would need approval;
- isolate a Claude Code agent from its host. The agent runs as your user; we give desk an empty home, a minimal environment and a working directory outside your home folder (see Platform findings).

Anyone who can talk to desk can try to make it reveal its environment, and its Claude Code token lives there. Only the demo people are in these rooms; give desk a token of its own before you let anyone else in.

## Platform findings

Found while building this on Switch 0.31.0. Each was seen on our stand; code references are to tag `switch-v0.31.0`.

1. **A person who may address an agent may also answer its approval cards** (`session_activity/service.py:571-602`). So the agent that holds data must not be addressable by the people who must not approve; that is why keeper and desk are separate agents.
2. **A Claude Code agent started by the controller loads its host's personal instructions.** Claude Code reads `.claude/CLAUDE.md` and `.claude/rules/` from every parent folder of its working directory, so an agent working under the owner's home folder gets the owner's private instructions in every session, whatever `HOME` it runs with. We found this in desk's transcript and moved desk's working directory to `/tmp`. The controller does not change `HOME` for agents, and the Claude adapter starts sessions with `strictMcpConfig: false`.
3. **Deleting a managed agent's Claude Code transcript breaks its room session**: Switch keeps resuming the old session id and logs "The session host hung up before it answered". Removing and recreating the managed agent fixes it.
4. **`AGENT_MANAGEMENT_ENABLED=true` stops switch-core 0.31.0 at startup**; agent management is now the feature flag `agent_management` in `FEATURE_FLAGS_ENABLED`.
5. **`.env.example` sets `SWITCH_VERSION=latest`** (line 23), although the standalone compose file requires an explicit version on purpose. A `.env` copied from the example follows `latest`, not the release you tested; `up.sh` pins 0.31.0.
6. **A chat account not linked to a Switch user gets a different refusal** ("this chat account isn't linked") instead of the room policy's; `seed.py` links every demo person.
7. **The room activity record (`/gateway/chats/{room}/activity`) returns 403 to the admin** until the admin joins that chat.
8. **Mattermost 11.9.0 is amd64-only** (the compose file sets `platform: linux/amd64`); on a Docker host without amd64 emulation it exits at once with `exec format error`.

## How AI was used

- desk is a Claude Code agent, run by Switch's agent controller (Tier B).
- keeper uses no language model, on purpose: what leaves the data store is decided by deterministic code.
- The code was written with Claude Code as a coding assistant, from a design we wrote and approved before the build window; every change was checked with the scripts in this repo (`verify.sh`, `tests/`).

## Disclosure

Everything in this repository was written during the hackathon window (first commit on 3 November 2026, 18:31 UTC). Switch is used as released (Apache-2.0 with the Commons Clause): `up.sh` downloads its compose file from the release tag and nothing of Switch is copied here. All customer data is synthetic (`data/generate.py`, seeded); no real customer, client or person appears.

## License

MIT, see [LICENSE](LICENSE).
