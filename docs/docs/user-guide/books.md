# Books

pyrate.media includes a books library with metadata from **Open Library** and a built-in reader — you can read EPUBs right in your browser, with your reading position synced across all your devices.

## The Books Library

Open **Books** in the navigation. Like the home page, the books page is built from configurable sections — for example a hero carousel, genre rows with a **See All** option, your favorite books, and a continue-reading row. In the library, books are grouped by author.

Books also show up in the global [search](search.md) with their own results section, and can be added to [lists](lists.md) and marked as [favorites](favorites.md) just like movies and shows — click the heart icon on a book to favorite it.

### Metadata

Book metadata comes from **Open Library** (openlibrary.org) and includes:

- Title and description
- Cover art
- Author names and photos
- Subjects and genres
- First publication date

## Reading a Book

Open a book's detail page and press **Read**. What happens next depends on the file format:

| Format | How it opens |
|--------|--------------|
| **EPUB** | pyrate.media's built-in reader |
| **PDF** | Your browser's built-in PDF viewer |
| Anything else (MOBI, AZW3, comic archives, …) | A **Download** button — save the file and open it in your favorite reading app |

!!! note "Book not on the server yet?"
    Just like movies and episodes, pressing **Read** on a book that has no file yet lets pyrate.media search the server's indexers and download it — you'll see the familiar waiting screen, and the book opens automatically once the download finishes. This depends on your administrator having download automation set up. See [Streaming & Playback](streaming.md) for how this works.

### The EPUB reader

The reader shows the book as pages on a dark, reading-friendly background. A bar along the bottom holds the page controls:

- The **‹** and **›** buttons turn to the previous or next page.
- Between them you'll see your position as a percentage, with a small progress bar underneath.

You can also turn pages from the keyboard:

| Key | Action |
|-----|--------|
| ++arrow-left++ | Previous page |
| ++arrow-right++ | Next page |

The keys work even while your cursor is inside the book text.

### Reading progress

Your position is saved automatically — every 30 seconds while you read, and again when you close the reader. When you come back to the book, it reopens at the exact spot where you left off, on any device you sign in from.

Books you've started also count toward your [viewing history](history.md), and appear in **Continue Watching** rows so you can jump back in with one click.

!!! tip
    Reading progress is stored per user on the server, not in your browser — so you can start a book on your desktop and pick it up on your phone or tablet.

## Downloading Book Files

For formats the built-in reader can't display, the reader offers a **Download** button instead — use it to save the file locally and read it in a dedicated app or on an e-reader.

## Next Steps

- [Search](search.md) — find books across your library
- [Favorites](favorites.md) — heart books to keep them close
- [Lists & Collections](lists.md) — organize books into lists
- [Viewing History](history.md) — where your reading progress lives
