# Quick Start

This guide helps you get up and running quickly with Pyrate.Media.

## First Login

After the [Installation](installation.md):

1. Open your browser and navigate to your Pyrate.Media instance
2. Log in with your credentials (or via OIDC)
3. You will see the dashboard

## Initial Setup

### 1. Activate Plugins

Before you can search for media, activate the metadata providers:

#### TMDB (for Movies & Shows)

1. Go to **Administration** → **Plugins**
2. Find **TMDB** in the list
3. Click **Configure**
4. Enter your TMDB API key
5. Click **Save**

#### IGDB (for Games)

1. Find **IGDB** in the plugin list
2. Click **Configure**
3. Enter Client ID and Client Secret
4. Click **Save**

### 2. Create Libraries

Create at least one library:

1. Go to **Administration** → **Libraries**
2. Click **New Library**
3. Choose the type:
   - **Movies** - For movies
   - **Shows** - For TV shows
   - **Games** - For video games
4. Enter a name
5. Configure the storage path (e.g., `/data/library/movies`)
6. Click **Create**

### 3. Set Up Indexers (Optional)

To search for and download releases:

1. Go to **Administration** → **Indexers**
2. Click **Add Indexer**
3. Choose the type (e.g., Newznab)
4. Configure:
   - **Name**: A name for the indexer
   - **URL**: The indexer URL
   - **API-Key**: Your API key
5. Click **Test Connection**
6. Click **Save**

### 4. Set Up Download Client (Optional)

To start downloads:

1. Go to **Administration** → **Downloader**
2. Click **Add Downloader**
3. Choose the client type:
   - **SABnzbd** - For Usenet
   - **Deluge** - For Torrents
4. Configure:
   - **Name**: A name for the client
   - **Host**: IP address or hostname
   - **Port**: Web interface port
   - **API-Key/Password**: Authentication
5. Click **Test Connection**
6. Click **Save**

## Adding Media

### Add a Movie

1. **Start a search**
   - Navigate to **Movies** in the menu
   - Use the search bar at the top
   - Type in the movie title

2. **Select a movie**
   - Browse the results
   - Click on the desired movie
   - View the details

3. **Add to library**
   - Click **Add to Library**
   - The movie will be added to your library

### Add a Show

1. **Search for a show**
   - Navigate to **Shows**
   - Search for the show
   - Click on the show

2. **Seasons & Episodes**
   - View the season overview
   - Click on a season for episodes
   - Each episode can be played individually

### Create a List

1. **Create a new list**
   - Click on **Lists** in the menu
   - Click **New List**
   - Enter a name (e.g., "Watchlist")
   - Choose the visibility (Private/Public)
   - Click **Create**

2. **Add media to the list**
   - Open a movie or show
   - Click **Add to List**
   - Select your list

## Playing Media

### Smart Play

Pyrate.Media uses "Smart Play" - the system automatically decides what to do:

1. **File available** → Streaming starts immediately
2. **Releases available** → Download is started
3. **No releases** → Search is started

### Play a Movie

1. Open a movie
2. Click **Play**
3. Depending on the status:
   - **Ready immediately**: Player opens
   - **Download in progress**: Progress indicator
   - **Search in progress**: Waiting screen

### Play an Episode

1. Open a show
2. Select the season
3. Click on an episode
4. Click **Play**

### In the Player

- **Pause/Play**: Spacebar or click
- **Fast forward/Rewind**: Arrow keys or slider
- **Fullscreen**: F or double-click
- **Volume**: Mouse wheel or volume slider

## Start a Watch Party

Watch together with friends:

1. **Create a party**
   - Open a media item
   - Click **Start Watch Party**
   - A party code is generated

2. **Share the code**
   - Share the 6-digit code with friends
   - Friends go to **Watch Parties** → **Join**
   - Enter the code

3. **Synchronized viewing**
   - The host controls playback
   - All participants are synchronized
   - Play/Pause/Seek applies to everyone

## Understanding the Interface

### Navigation

The side menu contains:

- **Dashboard**: Overview and recent activity
- **Movies**: Movie library
- **Shows**: Show library
- **Games**: Game library
- **Lists**: Your own collections
- **Administration**: System settings (admins only)

### Dashboard

The dashboard shows:

- **Trending**: Popular content
- **Recently Added**: New media
- **Lists**: Quick access to your lists

### User Menu

In the top right corner you will find:

- **Profile**: Your settings
- **Language Settings**: UI, audio, subtitles
- **Log Out**: Sign out

## User Settings

### Language Settings

1. Click on your profile picture
2. Select **Settings**
3. Configure:
   - **UI Language**: German or English
   - **Audio Language**: Preferred audio track
   - **Subtitle Language**: Preferred subtitles

### Edit Profile

- **Name**: Display name
- **Email**: Contact email
- **Password**: Only for local accounts (not OIDC)

## Tips

### Use Trending

1. The admin can import trending lists
2. Go to **Administration** → **Libraries**
3. Click **Import Trending** on a library
4. Popular movies/shows will be added to the library

### Use Search Effectively

- The search looks through titles and descriptions
- Elasticsearch enables fast full-text search
- Filter by media type in the search results

### Manage Downloads

1. Go to **Administration** → **Downloads**
2. View all active and completed downloads
3. Downloads can be deleted

## Next Steps

1. **[Dashboard](../user-guide/dashboard.md)** - All dashboard features
2. **[Movies](../user-guide/movies.md)** - Movie management in detail
3. **[Shows](../user-guide/shows.md)** - Show management in detail
4. **[Streaming](../user-guide/streaming.md)** - Streaming features
5. **[Administration](../administration/overview.md)** - Advanced settings
