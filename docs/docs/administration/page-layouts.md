# Page Layouts

Page Layouts control what content sections appear on the home page and each library page. This is how you customize the user experience - choosing which sections are shown, in what order, and with what configuration.

## Overview

Navigate to **Admin** -> **Page Layouts** to see all configured layouts.

Each layout has:

- **Name**: Descriptive name (e.g. "Home Page", "Movies Library")
- **Slug**: URL identifier (e.g. `home` for the default home page)
- **Library**: Optional - if set, this layout is used for a specific library page
- **Active**: Whether the layout is currently in use
- **Sections**: Number of configured sections

## Creating a Layout

1. Navigate to **Admin** -> **Page Layouts**
2. Click **Create Layout**
3. Fill in the details:
    - **Name**: A descriptive name
    - **Slug**: URL slug (use `home` for the default home page layout)
    - **Library**: Optionally assign to a specific library
    - **Active**: Toggle on/off
4. Click **Save**
5. After saving, you can add sections

!!! info "The Home Layout"
    The layout with slug `home` is the default home page layout shown to all users on the main page (`/`). Each library can have its own layout assigned.

## Section Types

Each section is a content block on the page. Available types:

### Hero Carousel

A large, animated carousel at the top of the page showing featured media with backdrop images, titles, and quick action buttons (Play, Details).

**Configuration:**

- **List**: Select a specific list to source items from, or leave empty for trending items

### Continue Watching

Shows media the user has started but not finished, with progress bars. Users can quickly resume playback.

**Configuration:**

- **Content Type**: Filter by type (movies, episodes, etc.) or show all

### Favorites

Displays the user's favorited media as a horizontal poster carousel.

### Genre Section

Shows media from a specific genre as a horizontal poster row.

**Configuration:**

- **Genre**: Select which genre to display (required)
- **Max Items**: Maximum number of items to show (1-50)

### All Genres

Automatically shows all genres with items, each as its own horizontal row.

**Configuration:**

- **Max Items per Genre**: How many items to show per genre row (1-50)

### List Section

Shows items from a specific list (user list or system list).

**Configuration:**

- **List**: Select which list to display (required)

### Dynamic Search

Shows results based on configurable search/filter criteria.

**Configuration:**

- **Media Type**: Filter by type
- **Genre**: Filter by genre(s)
- **Year From/To**: Filter by release year range
- **Sort By**: How to sort results
- **Sort Order**: Ascending or descending
- **Query**: Optional search query

## Managing Sections

### Adding a Section

1. Open a layout's edit page
2. Click **Add Section**
3. Select the **Section Type**
4. Give it an optional **Title** (displayed as the section header)
5. Configure type-specific settings
6. Click **Save**

### Reordering Sections

Use the **up/down arrows** next to each section to change its position. The order determines the display order on the page.

### Enabling/Disabling Sections

Toggle the switch next to a section to show or hide it without deleting it.

### Editing a Section

Click the **pencil icon** to modify a section's configuration.

### Deleting a Section

Click the **trash icon** and confirm to permanently remove a section.

## Example Layout Configuration

A typical home page layout might have:

1. **Hero Carousel** - Trending movies from a system list
2. **Continue Watching** - User's in-progress media
3. **Favorites** - User's favorited items
4. **All Genres** - Browse by genre with 10 items each

A library-specific layout (e.g. for Movies) might have:

1. **Hero Carousel** - Featured movies
2. **Continue Watching** - Filtered to movies only
3. **Genre: Action** - Action movies
4. **Genre: Comedy** - Comedy movies
5. **List: Trending Movies** - System trending list
6. **Dynamic Search** - New releases from the past year, sorted by release date
