# Library Management

Libraries are the core of Pyrate.Media. Each library manages a specific media type and has its own settings for storage paths, downloads, and file naming.

## Creating a Library

1. Navigate to **Admin** -> **Create Library** (or click "+" in the sidebar)
2. Select the **library type**:
    - **Movies** (MOVIES)
    - **Shows** (SHOWS)
    - **Music** (MUSIC)
    - **Games** (GAMES)
    - **Books** (BOOKS)
3. Enter a **name** (e.g. "My Movies")
4. Configure the **storage path** (absolute path in the Docker container, e.g. `/data/library/movies`)
5. Click **Create**

!!! warning "Docker Volumes"
    The storage path must be accessible inside the Docker container. Ensure the corresponding volume is properly mounted.

## Library Settings

Open a library's settings from the admin sidebar or dashboard.

### General Configuration

| Setting | Description | Available for |
|---------|-------------|---------------|
| **Enable Library** | Toggles the library on/off | All |
| **Library Path** | Absolute path to media file storage | All |
| **On-Demand Downloads** | Enables Smart Play - automatic download when playing | Movies, Shows, Music |
| **Prefetch Downloads** | Automatically downloads new episodes when available | Shows only |
| **Hide Season Zero** | Hides special episodes (Season 0) in the UI | Shows only |
| **Allowed Languages** | Which languages to consider during release searching | Movies, Shows |

### Naming Schema

Configure how downloaded files and folders are named.

#### Available Variables

**Movies:**

- `{title}` - Movie title
- `{year}` - Release year
- `{tmdb_id}` - TMDB ID
- `{imdb_id}` - IMDB ID
- `{quality}` - Quality (1080p, etc.)

**Shows:**

- `{title}` - Series title
- `{year}` - Start year
- `{season}` - Season number (use `:02` for zero-padding)
- `{episode}` - Episode number
- `{episode_title}` - Episode title

#### Options

- **Replace Illegal Characters**: Replaces characters not allowed in file names
- **Colon Replacement**: What to use instead of `:` (e.g. ` - `)

#### Preview

Click **Preview** to see how an example filename would look with your schema. The preview shows:

- **Folder**: e.g. `The Matrix (1999)`
- **Filename**: e.g. `The Matrix (1999).mkv`
- **Full Path**: The combination of both

### Download Rules (Scoring)

Download rules determine which releases are preferred. The system assigns **points (score)** to each release based on configurable rules.

Each rule consists of:

| Field | Description |
|-------|-------------|
| **Label** | Descriptive name (e.g. "Prefer 1080p") |
| **Regular Expression** | Pattern applied to the release name |
| **Score** | Points assigned (positive = preferred, negative = avoided) |
| **Enabled** | Whether the rule is active |
| **Inverted** | Reverses the rule (points when pattern does NOT match) |

**Examples:**

- `1080p` with Score +10 -> Prefers 1080p releases
- `CAM|TELESYNC|TS` with Score -100 -> Avoids camera rips
- `x265|HEVC` with Score +5 -> Slight bonus for more efficient encoding

### Advanced Scoring Configuration

For advanced users, the **Scoring Configuration** panel offers detailed weight settings:

**Categories:**

- **Resolution**: Weights for 2160p, 1080p, 720p, 480p
- **Source**: Weights for BluRay, WEB-DL, HDTV, etc.
- **Codec**: Weights for x265, x264, AV1, etc.
- **Audio**: Weights for DTS-HD, TrueHD, FLAC, AAC, etc.

**Bonuses:**

- HDR bonus, Dolby Vision bonus
- Remux bonus (movies only)
- PROPER/REPACK bonus
- Trusted release group bonus

**Trusted Groups:** List of release groups that receive bonus points.

**Blocked Groups:** List of release groups that are excluded from results.

### Import Trending

For each library you can **import trending content**:

1. Open the library settings
2. Click **Import Trending**
3. The system fetches current trending data from the metadata provider:
    - TMDB for movies and shows
    - IGDB for games
4. Media items are added to the library
5. A system list is created (e.g. "Trending Movies")

### Scan Library

The **Scan** button searches the library path for existing media files and imports them into the database.
