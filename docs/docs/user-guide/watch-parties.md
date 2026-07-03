# Watch Parties

Watch Parties enable synchronized streaming - you watch the same movie or episode together with friends, synchronized in real time.

## Creating a Watch Party

### From the Player

1. Open a movie or an episode
2. Start playback
3. In the player you will find the **Watch Party** button
4. A party is created with a **6-digit code**
5. Share the code with your friends

### From the Toolbar

In the header there is a Watch Party button that shows you active parties and allows creating/joining.

## Joining a Watch Party

1. Click the **Watch Party** button in the toolbar
2. Select **Join**
3. Enter the 6-digit party code
4. You will be added to the party and see the same medium as the host

### Party Codes

- 6-digit, alphanumeric (e.g. `ABC123`)
- Case insensitive
- Valid as long as the party is active

## Roles

### Host (Creator)

As host, you control playback for everyone:

- **Play/Pause**: Starts and stops for all participants
- **Seek**: Jumps to the desired position for everyone
- **End Party**: Ends the watch party for everyone

### Participant

As a participant:

- You see the same medium as the host
- Your position is automatically synchronized
- You can **leave** the party at any time

## Synchronization

The watch party keeps all participants in sync:

- **Real-time updates** via WebSocket connection
- **Drift correction**: Small deviations are smoothly compensated
- **Hard sync**: For large deviations, the position is corrected

### Heartbeat

Your browser regularly sends a signal to the server to show that you are still connected. If the signal is absent (e.g. when the tab is in the background), you are shown as offline.

## Watch Party Controls

In the player, additional controls appear for watch parties:

- **Participant list**: Shows who is currently watching
- **Sync status**: Shows whether everyone is in sync
- **Leave/End party**: Depending on your role

## Tips

- **Stable connection**: Ensure good internet for both you and your friends
- **Start together**: Wait until everyone has joined before the host starts
- **Modern browser**: Use up-to-date browsers for the best compatibility
- **Communication**: Use an external chat/voice channel (e.g. Discord) for conversation

## Limitations

- Only one medium per party
- No integrated video or audio chat functionality
- Mobile browsers may have limitations with background tabs

## Next Steps

- [Streaming](streaming.md) - How playback works
- [Friends & Invitations](friends.md) - Invite friends
- [Movies & Series](movies.md) - Discover media
