# Favorites & Likes

Favorites give you one-click access to the media you care about most — and on servers where it is enabled, favoriting something tells streamarr.media to fetch and maintain it for you automatically. Likes are a lighter signal: a quick thumbs-up for individual items and for other users' lists.

## Marking Media as a Favorite

You can toggle a favorite in two places:

- **On the detail page** — open a movie, show, game, album, or book and click the **heart button**. It fills in red when the item is a favorite; click again to remove it.
- **In the video player** — the player controls include the same heart button, so you can favorite what you are currently watching.

!!! tip "Episodes count for the whole show"
    Favoriting an episode or a season marks the **entire show** as a favorite. The same applies to songs and albums, which roll up to their artist or album.

## Viewing Your Favorites

Your favorites are kept in a personal **Favorites** list that is created automatically and cannot be deleted:

- Open the **side menu** and pick **Favorites** under **My Lists**
- Or navigate directly to `/favorites`

The list page offers a **grid view** (poster wall) and a **table view** with sortable columns for title, type, and year. Use the remove action to take an item off the list — this is the same as clicking the heart again.

Your favorites can also appear elsewhere:

- **Home page** — if your home layout contains a Favorites section, they show up as a **My Favorites** row. See [Dashboard & Home](dashboard.md).
- **Search results** — the filter bar has a **Favorite** filter with **Favorites only** and **Not favorites** options. See [Search](search.md).
- **Recommendations** — what you favorite feeds into your personal recommendations, and can surface in your friends' suggestions too.

## Auto-Download of Monitored Favorites

On servers with download automation, favorites can do more than bookmark. If the administrator has enabled **Favorites Automation** and your account has the *keep favorites* permission, favoriting an item marks it as **monitored**:

| | Favorite as bookmark | Monitored favorite |
|---|---|---|
| Quick access via the Favorites list | Yes | Yes |
| Missing content is searched and downloaded | No | Yes — including every episode of a favorited show |
| Existing files upgraded to better releases | No | Yes, as better releases appear |
| Protected from automatic library cleanup | No | Yes |

You can tell a favorite is monitored by the small **download badge** on the heart button; its tooltip reads *"Monitored — auto-downloading & upgrading"*.

!!! note "Depends on server configuration"
    All automation switches are **off by default** and permission-gated. If the badge never appears for you, your server either has automation disabled or your account does not have the required permission — ask your administrator.

!!! info "Removing a monitored favorite"
    Unfavoriting stops the monitoring and upgrading for that item. It never deletes files that were already downloaded.

## Likes

Next to the heart, playable items (movies, episodes, songs, games, books) have a **thumbs-up button**. Liking is a lightweight way to mark things you enjoyed without managing lists:

- Liked items are collected automatically in a **Liked Media** list under **My Lists**.
- Container pages such as shows, seasons, artists, and albums do not have a like button — like the individual items instead.

### Liking Lists

You can also like **other users' public lists**. Open a list you do not own and click the **heart icon** in its header — the list's like count is shown as a chip next to its details. You cannot like your own lists.

## Next Steps

- [Lists & Collections](lists.md) — create and share your own lists
- [Viewing History](history.md) — everything you have watched so far
- [Dashboard & Home](dashboard.md) — customize your home page sections
