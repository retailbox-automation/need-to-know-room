#!/usr/bin/env python3
"""Seed the Need-to-Know Room workspace on a stack started by scripts/up.sh.

Idempotent: run it as many times as you like. It creates or reuses:
  * three Mattermost people: alex (owner), sam (employee), dana (contractor);
  * a link from alex's Mattermost account to the Switch admin, so Switch knows
    alex is the owner of the agents (owner-only addressing depends on it);
  * keeper, a scripted Switch agent (no LLM) that holds the customer data,
    registered through the agent bridge with a personal registration key so it
    belongs to the same owner as everything else;
  * three private rooms bridged to Mattermost: #core, #contractors, #owner-desk;
  * keeper's addressing policy: who may talk to keeper, room by room.

Everything it learns (ids, keys, passwords of the demo people) goes to
.stand/state.json (mode 600), which keeper, verify.sh and audit.py read.
"""
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from switchlib import ApiError, Stand, load_state, save_state  # noqa: E402

PEOPLE = {
    "alex": {"first_name": "Alex", "last_name": "Morgan", "nickname": "owner"},
    "sam": {"first_name": "Sam", "last_name": "Patel", "nickname": "sales"},
    "dana": {"first_name": "Dana", "last_name": "Lee", "nickname": "contractor"},
}
ROOMS = {
    "core": {"people": ["alex", "sam"],
             "description": "Employees. Customer data may be shared here."},
    "contractors": {"people": ["alex", "dana"],
                    "description": "Contractors and the desk assistant."},
    "owner-desk": {"people": ["alex"],
                   "description": "Owner only. Approvals for data requests."},
}
KEEPER_PROFILE = {
    "connection_model": "always_on",
    "message_exchange": True,
    "pre_invocation_mediation": [],
    "post_invocation_mediation": [],
    "event_reporting": [],
}


def keeper_policy(room_ids):
    """Who may address keeper, room by room. Any rule that matches allows it.

    Dimensions default to "*" (anyone), so users/agents are spelled out as []
    wherever they must not get through.
    """
    return {"rules": [
        # #core: every person in the room may ask keeper; no agent may.
        {"rooms": [room_ids["core"]], "users": "*", "agents": []},
        # #contractors: only the owner and the owner's own agents (desk).
        # Dana is in the room but matches no rule, so Switch refuses her.
        {"rooms": [room_ids["contractors"]], "users": [], "agents": [],
         "owner": True, "owner_agents": True},
        # #owner-desk: only the owner.
        {"rooms": [room_ids["owner-desk"]], "users": [], "agents": [], "owner": True},
    ]}


def ensure_people(stand, state):
    env = stand.env
    token = stand.mm_login(env["MATTERMOST_ADMIN_USER"], env["MATTERMOST_ADMIN_PASSWORD"])
    team = stand.mm_call("GET", "/teams/name/" + env.get("MATTERMOST_TEAM_NAME", "switch"), token)
    people = state.setdefault("people", {})
    for username, profile in PEOPLE.items():
        person = people.get(username, {})
        password = person.get("password") or secrets.token_urlsafe(18)
        try:
            user = stand.mm_call("GET", "/users/username/" + username, token)
            # Known account but we lost its password: reset it as the admin.
            if not person.get("password"):
                stand.mm_call("PUT", "/users/%s/password" % user["id"], token,
                              {"new_password": password})
        except ApiError as exc:
            if exc.status != 404:
                raise
            user = stand.mm_call("POST", "/users", token, dict(
                profile, username=username, password=password,
                email="%s@n2k.example" % username))
        stand.mm_call("PUT", "/users/%s/patch" % user["id"], token, profile)
        stand.mm_call("POST", "/teams/%s/members" % team["id"], token,
                      {"team_id": team["id"], "user_id": user["id"]})
        people[username] = {"id": user["id"], "password": password}
    print("people: " + ", ".join("@" + p for p in people))


def mattermost_bridge(stand):
    for bridge in stand.gw("GET", "/collaborations"):
        if bridge["bridge_type"] == "mattermost":
            return bridge["bridge_id"]
    raise RuntimeError("no Mattermost bridge; did scripts/up.sh finish?")


def link_people(stand, state, bridge_id):
    """Tie each Mattermost account to a Switch user, the way a real team is set up.

    alex is linked to the Switch admin, who owns the agents, so owner-only
    rules recognise alex. sam and dana get ordinary Switch accounts of their
    own: then a refusal is Switch saying "you may not", not "I can't tell who
    you are".
    """
    linked = stand.gw("GET", "/auth/me/identities")
    alex = state["people"]["alex"]
    if not any(i["external_user_id"] == alex["id"] for i in linked):
        stand.gw("POST", "/collaborations/%s/identities" % bridge_id,
                 {"external_user_id": alex["id"], "username": "alex"})
    print("link: @alex -> Switch admin (the agents' owner)")
    switch_users = {u["email"]: u for u in stand.gw("GET", "/users")}
    for username in ("sam", "dana"):
        person = state["people"][username]
        email = "%s@n2k.example" % username
        user = switch_users.get(email)
        if user is None:
            user = stand.gw("POST", "/users", {
                "name": PEOPLE[username]["first_name"] + " " + PEOPLE[username]["last_name"],
                "email": email, "password": secrets.token_urlsafe(18), "role": "user"})
        person["switch_user_id"] = user["id"]
        stand.gw("POST", "/collaborations/%s/identities" % bridge_id,
                 {"external_user_id": person["id"], "username": username,
                  "user_id": user["id"]})
        print("link: @%s -> Switch user %s" % (username, email))


AGENTS = {
    "keeper": "Holds the customer list. Hands out one field, once, after the owner approves.",
    "desk": "Helps contractors. Holds no customer data; asks keeper.",
}


def ensure_agent(stand, state, name):
    """Register a scripted agent through the agent bridge, owned by the admin.

    The registration key is a personal key of the Switch admin, so the agent's
    owner is the admin, the same person alex is linked to. keeper's rule
    "owner_agents" relies on keeper and desk having that same owner.
    """
    agent = state.get(name)
    registered = {a["name"] for a in stand.gw("GET", "/agents")}
    if agent and name in registered:
        print("%s: already registered (%s)" % (name, agent["id"]))
        return agent
    if "registration_key" not in state:
        state["registration_key"] = stand.gw("POST", "/api-keys",
                                             {"label": "need-to-know-room seed"})["key"]
    result = stand.agent("POST", "/agents", state["registration_key"], {
        "name": name, "display_name": name, "description": AGENTS[name],
        "connector_type": "custom", "integration_profile": KEEPER_PROFILE, "overwrite": True,
    })
    agent = {"id": result["id"], "api_key": result["api_key"]}
    state[name] = agent
    print("%s: registered (%s)" % (name, agent["id"]))
    return agent


def ensure_rooms(stand, state, bridge_id):
    existing = {r["name"]: r for r in stand.gw("GET", "/rooms")}
    room_ids = {}
    for name, spec in ROOMS.items():
        room = existing.get(name)
        if room is None:
            room = stand.gw("POST", "/rooms", {
                "name": name,
                "description": spec["description"],
                "channel_type": "channel_private",
                "bridge_id": bridge_id,
                "agent_names": ["keeper"],
                "user_names": spec["people"],
            })
            print("room: created #%s (%s)" % (name, room["id"]))
        else:
            print("room: #%s exists (%s)" % (name, room["id"]))
        room_ids[name] = room["id"]
    state["rooms"] = room_ids
    return room_ids


def desk_policy(room_ids):
    """desk answers anyone in #contractors, and no agent: keeper's replies
    must not wake desk, or the two would talk to each other forever."""
    return {"rules": [{"rooms": [room_ids["contractors"]], "users": "*", "agents": []}]}


def main():
    desk_mode = "claude" if "--desk" in sys.argv and "claude" in sys.argv else "stub"
    stand = Stand()
    state = load_state()
    state["owner"] = "alex"
    ensure_people(stand, state)
    save_state(state)
    bridge_id = mattermost_bridge(stand)
    state["bridge_id"] = bridge_id
    link_people(stand, state, bridge_id)
    keeper = ensure_agent(stand, state, "keeper")
    save_state(state)
    room_ids = ensure_rooms(stand, state, bridge_id)
    save_state(state)
    stand.gw("PUT", "/agents/%s/addressing-policy" % keeper["id"],
             {"policy": keeper_policy(room_ids)})
    print("keeper policy: set for #core, #contractors, #owner-desk")
    if desk_mode == "stub":
        # Tier A: a scripted desk, so the workflow runs with no model account.
        # Tier B (agents/desk/README.md) replaces it with a Claude Code desk.
        desk = ensure_agent(stand, state, "desk")
        save_state(state)
        stand.gw("POST", "/rooms/%s/agents" % room_ids["contractors"], {"agent_ids": [desk["id"]]})
        stand.gw("PUT", "/agents/%s/addressing-policy" % desk["id"], {"policy": desk_policy(room_ids)})
        print("desk (scripted): in #contractors, answers people only")
    # Switch keeps each room's approvals (who answered what, and when) and
    # serves them to the room's members. The admin joins each room's chat so
    # scripts/audit.py can read that record.
    me = stand.gw("GET", "/auth/me")
    for room_id in room_ids.values():
        stand.gw("POST", "/chats/%s/members" % room_id, {"user_id": me["id"]})
    print("audit: the admin can read each room's approval record")
    save_state(state)
    print("state written to .stand/state.json")


if __name__ == "__main__":
    main()
