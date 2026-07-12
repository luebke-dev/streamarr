# Watch Parties

Watch parties let you watch the same movie or episode together with friends — playback stays synchronized in real time for everyone, no matter where they are.

Everything happens through the **Party** button (the people icon) in the top toolbar. It is available on every page and shows a badge with the member count while you are in a party.

## Creating a party

1. Click the **Party** button in the toolbar and choose **Create**
2. Optionally give the party a name (e.g. *Movie Night*)
3. Decide whether to enable **Allow others to control** — when enabled, all members can play, pause, and seek; otherwise only you as the host
4. Click **Create** — you get a six-character **party code** to share with your friends

If you create the party while you are already watching something, that title automatically becomes the party's media. Otherwise the party starts empty: as soon as you (the host) start playing a movie or episode, it becomes the party's title and all members are taken to it automatically.

!!! tip "Guest control"
    The **Allow others to control** setting is chosen when the party is created. Leave it off for a classic "host runs the show" experience, or turn it on so everyone can pause when someone needs a snack break.

## Joining a party

There are two ways to join:

=== "With a party code"

    1. Click the **Party** button in the toolbar and choose **Join**
    2. Enter the six-character code the host shared with you
    3. You join the party — if it is already watching something, you are taken straight to playback at the current position

=== "From your friends' parties"

    If a [friend](friends.md) is hosting an active party, it appears under **Friends' Parties** in the Party menu — click it to join without typing a code.

### Party codes

- Six characters, letters and numbers
- Not case sensitive
- Valid as long as the party is active

## Host and members

| Action | Host | Member |
|--------|------|--------|
| Play, pause, seek for everyone | Yes | Only if guest control is enabled |
| Switch to a different movie or episode | Yes (everyone follows) | No |
| Remove a member from the party | Yes | No |
| Copy and share the party code | Yes | Yes |
| Leave the party | Yes — ends the party for everyone | Yes — the party continues |

!!! warning "The host leaving ends the party"
    There is no separate "end party" step: when the host leaves, the session ends and all members are disconnected.

## How synchronization works

- Play, pause, position, and playback speed are pushed to all members in real time
- Small timing differences (under a couple of seconds) are tolerated; if you drift further, your player jumps back to the shared position
- The host's position is re-broadcast periodically, so anyone joining late lands at the right spot
- When you join a party mid-playback, the party position is used for resume — not your personal viewing history

Each participant streams the title with their own account and their own quality settings, so one member's slow connection does not degrade the picture for everyone else. See [Streaming & Playback](streaming.md) for how playback itself works.

## The Party menu

While you are in a party, the toolbar **Party** button shows:

- The party name and the **party code**, with a copy-to-clipboard button
- The **member list**, with a **Host** badge and a live **Connected** / **Disconnected** status per member
- **Remove Member** buttons (host only)
- **Leave Party**

Your app regularly signals the server that you are still there; if that signal stops (for example, a closed laptop), you appear as *Disconnected* to the others.

## Limitations

- One title at a time — the whole party watches the same movie or episode
- Watch parties are for video (movies and episodes)
- No built-in text, voice, or video chat — use an external channel such as Discord alongside
- Every participant needs their own account on the server and access to the title
- Server administrators can see and end any active party

## Next steps

- [Streaming & Playback](streaming.md) — how playback works
- [Friends & Invites](friends.md) — add friends to see their parties
- [Movies & Shows](movies.md) — find something to watch together
