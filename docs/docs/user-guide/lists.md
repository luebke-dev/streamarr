# Lists & Collections

Lists let you organize, collect, and share media with others. A single list can mix every media type on the server — movies, shows, games, music, and books.

## List Types

### User Lists

Lists created by you. You have full control:

- Change name, description, visibility, and tags
- Add and remove any media
- Delete the list when it is no longer needed

### System Lists

Lists maintained automatically by the server:

- Trending lists imported from metadata providers (e.g. trending movies from TMDB or popular games from IGDB), refreshed on a schedule
- Collections that admins build from rules ("smart collections"), which are kept up to date automatically
- Marked with a **System** badge; only admins can change them

!!! note "Admin-curated collections"
    Admins can define rule-based collections that rebuild themselves on a schedule — for example "4K movies added this month". They appear to you as regular system lists. See [Smart Collections](../administration/smart-collections.md).

## Creating a List

=== "From the side menu"

    1. Open the side menu
    2. Next to the **My Lists** header, click the **+** button (*Create new list*)
    3. Enter a name and confirm
    4. The list is created as a **private** user list and opens immediately

=== "While adding media"

    The **Add to List** dialog on any detail page has a **Create new list** field at the bottom. Type a name and confirm — the list is created and the media is added to it in one step.

## Adding Media to Lists

From a **detail page**:

1. Open the detail page of a movie, show, game, album, or book
2. Click **Add to List**
3. A dialog shows your lists (with a search box once you have more than a few)
4. Select a list — the item is added

From the **list page** itself:

1. Open your list and click **Add Items**
2. Search for media in the dialog
3. Click **Add** next to a result; items already in the list are marked **In list**

To remove an item, hover over its poster and click the **×** button, or use the remove button in table view. Only the list owner (or an admin) can add and remove items.

## Viewing Your Lists

Your lists appear in the side menu under **My Lists**. Filter tabs above the list — **All** plus one tab per enabled media type — narrow it down to lists containing that type.

The list page itself offers:

- A toggle between a **poster grid** (with *Load more*) and a compact **table** view
- Info chips: visibility, item count, likes, tags, and — on public lists — the owner

## Editing a List

1. Open your list and click the **pencil** button (*Edit List*)
2. Change **Name**, **Description**, **Visibility**, and **Tags** (comma-separated); an expandable **Translations** section lets you provide the name and description per interface language
3. Click **Save**

Deleting works from the same page via the **trash** button — you will be asked to confirm, and deletion cannot be undone.

## Visibility & Sharing

| Visibility | Who can see it |
|------------|----------------|
| **Private** | Only you |
| **Unlisted** | Anyone you give the link to |
| **Public** | Everyone on the server |

- Public lists show up in [search results](search.md) in their own **Lists** section, and display a *by &lt;user&gt;* chip so people know who curated them.
- Other users can **like** your public and unlisted lists with the heart button; you cannot like your own lists.
- Depending on the [home page layout](dashboard.md) configured by your admin, lists can also appear as rows on the home page.

!!! tip "Share by link"
    Set a list to **Unlisted** to share it with friends via its link without making it visible to the whole server.

## Playlists

A playlist is a list that can be played through as a queue. A playlist opens on the same page as a regular list but adds a **Play playlist** button:

- If the playlist contains **only music**, all tracks are loaded into the persistent [music player](music.md) queue.
- For **video or mixed content**, playback starts with the first item, and the player's next/previous buttons step through the playlist in order.

!!! note
    The **+** button under *My Lists* creates regular lists, not playlists — there is no dedicated "New playlist" button in the app yet.

## List Ideas

- **Watchlist**: movies and shows you still want to watch
- **Favorite genre**: "Best Sci-Fi Movies", "Horror Classics"
- **Theme night**: "Movie Night Selection", "Sunday Shows"
- **Game backlog**: "Backlog", "Completed", "Currently Playing"

## Next Steps

- [Favorites](favorites.md) — quick access to favorite media without extra lists
- [Search](search.md) — find media and public lists
- [Music](music.md) — the audio player and its queue
