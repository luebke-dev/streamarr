# Streaming & Playback

Pyrate.Media offers integrated video streaming directly in the browser. The system automatically decides the best way to play a medium.

## Smart Play

Smart Play is the heart of playback. When you press **Play**, the following happens automatically:

```
File available?
 +-- YES --> Start streaming (Status: "streamable")
 +-- NO --> Download already running?
              +-- YES --> Waiting screen with "Stream is being prepared"
              +-- NO --> Releases available?
                           +-- YES --> Download best release
                           +-- NO --> Search indexers for releases
```

### Status Indicators

While Smart Play is working, you will see various states:

| Status | What happens | What you see |
|--------|-------------|---------------|
| Preparing | System checks availability | Spinner with poster/title of the medium |
| Downloading | File is being downloaded | "Stream is being prepared" with spinner |
| No Release | No downloads found | Notice with "Search Releases" button |
| Error | Something went wrong | Error message with retry button |
| Ready | Stream is available | Video player starts |

### Preparation Screen

During preparation, the system shows:

- Poster or still image of the medium
- Title (for episodes: series title + S01E03 notation)
- Description
- Animated spinner
- "Cancel" button to go back

## The Video Player

Pyrate.Media uses its own player with custom controls built on Video.js.

### Controls

- **Play/Pause**: Click on the video or the play button
- **Timeline/Progress bar**: Shows current position, clickable to jump
- **Volume**: Slider + mute button
- **Fullscreen**: Switch to fullscreen mode
- **Back button**: Exits the player
- **Favorite button**: Mark/unmark medium as favorite

### Episode Controls

For series episodes, additional buttons appear:

- **Previous Episode** (if available)
- **Next Episode** (if available)
- Display of series title and episode (e.g. "S02E05 - Episode Title")

### Stream Information

In the player, you can view information about the current stream:

- Available audio tracks (with language selection)
- Quality options

### Seek (Jumping)

When you jump to a position in the timeline:

1. The current transcode process is stopped
2. A new transcode starts from the desired position
3. The stream resumes seamlessly

Jumping takes a few seconds, as a new FFmpeg container is started.

## Transcoding

Videos are transcoded in real time for the browser:

- **Format**: HLS (HTTP Live Streaming) with .m3u8 playlists and .ts segments
- **Container**: FFmpeg runs in a Docker container
- **Codecs**: h264, h265, vp9 (depending on configuration)
- **Audio**: AAC, Opus, or MP3

### Audio and Subtitle Selection

The system automatically selects based on your language settings:

1. **Audio track**: Your preferred audio language is selected
2. **Subtitles**: If desired, subtitles are burned directly into the video

You can change your language preferences in the [User Settings](settings.md).

## Playback History

Your progress is saved automatically:

- **Position**: Where you are in the video
- **Progress**: Percentage display
- **Completed**: Marked when you have reached the end

This way you can later continue watching exactly where you left off. Your history is accessible via the menu under **History**.

## Troubleshooting

### Stream does not start

- Check if the file is available
- Check your internet connection
- Try again with the retry button

### Poor quality

- Check the source file (some releases are low quality)
- The admin can adjust the transcoding settings

### Buffering/Stuttering

- Reduced quality settings may help
- Check the network connection between you and the server

## Next Steps

- [Watch Parties](watch-parties.md) - Stream together
- [Movies & Series](movies.md) - Back to media management
- [Settings](settings.md) - Language and audio preferences
