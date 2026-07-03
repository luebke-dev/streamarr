# Transcoding Settings

Transcoding converts media files on-the-fly into a browser-compatible format (HLS) for streaming. It runs inside Docker containers using FFmpeg.

## Configuration

Navigate to **Admin** -> **Transcoding** to configure streaming settings.

### General Settings

| Setting | Description |
|---------|-------------|
| **Enable Transcoding** | Master switch for the entire transcoding system. When disabled, no streaming is possible. |
| **FFmpeg Docker Image** | The Docker image used for transcoding (e.g. `linuxserver/ffmpeg`). Must have FFmpeg installed. |
| **Temp Path** | Directory where temporary HLS segments are stored. Needs sufficient disk space. |

### Video Settings

| Setting | Description |
|---------|-------------|
| **Allowed Video Codecs** | Which codecs can be used for output: H.264, H.265/HEVC, VP9 |
| **Max Resolution** | Maximum output resolution: 480p, 720p, 1080p, 4K |
| **Default Video Bitrate** | Target bitrate for video encoding. Leave empty to use CRF mode. |
| **Default CRF** | Constant Rate Factor (0-51). Lower = better quality, larger file. Default: 23. Only used when no bitrate is set. |

### Audio Settings

| Setting | Description |
|---------|-------------|
| **Allowed Audio Codecs** | Which audio codecs can be used: AAC, Opus, MP3 |
| **Default Audio Bitrate** | Target audio bitrate (e.g. 128k, 192k, 256k) |
| **Default Audio Channels** | Number of audio channels (2 for stereo, 6 for 5.1 surround) |

### Hardware Acceleration

| Setting | Description |
|---------|-------------|
| **Enable Hardware Acceleration** | Use GPU for encoding/decoding |
| **Hardware Device** | Path to GPU device (e.g. `/dev/dri/renderD128` for Intel/AMD) |
| **Hardware Acceleration Type** | VAAPI, NVENC (NVIDIA), QSV (Intel QuickSync) |

!!! info "Hardware Acceleration Setup"
    For hardware acceleration to work:

    1. The GPU device must be passed through to the Docker container
    2. The FFmpeg image must include GPU drivers/libraries
    3. The correct acceleration type must be selected

    **NVIDIA**: Requires `nvidia-docker2` and an FFmpeg image with NVENC support.

    **Intel/AMD**: Requires `/dev/dri` device passthrough and an FFmpeg image with VAAPI support.

### Advanced Settings

| Setting | Description |
|---------|-------------|
| **Segment Duration** | Length of each HLS segment in seconds (default: 4) |
| **Playlist Size** | Number of segments in the HLS playlist |

## How Transcoding Works

```
Source File (MKV/MP4/AVI)
    |
    v
FFmpeg in Docker Container
    |
    v
HLS Playlist (.m3u8) + Segments (.ts)
    |
    v
Video.js Player in Browser
```

1. User clicks Play on a media item
2. A Docker container with FFmpeg is started
3. FFmpeg reads the source file and outputs HLS segments
4. Segments are written to the temp directory
5. The browser player requests the playlist and segments
6. When the user seeks, the old container is stopped and a new one starts from the seek position
7. When playback stops, the container is cleaned up and temp files are deleted

## Monitoring Active Sessions

Navigate to **Admin** -> **Active Sessions** to see currently running transcoding sessions:

- **User** who is streaming
- **Media** being watched
- **Video/Audio Codec** being used
- **Resolution** of the output
- **Duration** of the session
- **Stop** button to kill a session

## Tips

- Start with CRF mode (no fixed bitrate) for automatic quality scaling
- CRF 18-21 = high quality, CRF 23-26 = medium quality, CRF 28+ = low quality
- Monitor your temp directory space - active streams can consume several GB
- Hardware acceleration significantly reduces CPU usage and improves stream start time
- If streams buffer, try reducing the max resolution or increasing the CRF value
