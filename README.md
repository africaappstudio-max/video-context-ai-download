<p align="center"><img src="assets/logo.png" width="120" alt="Understand This Video Plugin logo"></p>

# Understand This Video Plugin

**Let any AI watch and hear a video.** Give Claude, Cursor, Grok Bot or any MCP client a video file on your computer, and it gets back what it can actually read:

- 6–12 **timestamped key frames** (scene changes, duplicates removed, small JPEGs)
- a **timestamped transcript** (local Whisper)
- one **contact-sheet image** with all frames in a grid
- one `context.md` timeline mixing what was shown and what was said

Everything runs **100% on your computer**. Your videos never leave it. This plugin only processes local video files. It does not download videos from the internet. If you have a video online, download or export it first, then give the plugin the file path.

## Price
**$49 one-time. Lifetime license, up to 3 of your devices.** No subscription.
Buy: https://understandvideo.shipmonthly.com

No refunds for change of mind. If it won't work on your computer, email me within 7 days and I'll fix it or refund you.

## Install: pick your app

You need your **license key** (it's in your purchase email). Buy one at https://understandvideo.shipmonthly.com. Works on Mac and Windows.

**Install in 3 steps (no Terminal):**
1. **Download the installer** for your computer: [Mac](https://github.com/africaappstudio-max/video-context-ai-download/releases/latest/download/Install-Understand-This-Video-Mac.zip) or [Windows](https://github.com/africaappstudio-max/video-context-ai-download/releases/latest/download/Install-Understand-This-Video-Windows.bat), then double-click it. *Mac:* if it says the file can't be opened, right-click it, choose **Open**, then **Open** again. *Windows:* if a blue box appears, click **More info**, then **Run anyway**.
2. **Paste your license key** in the box that pops up (it is in your purchase email). The installer adds everything else for you (ffmpeg, Python, transcript tools).
3. **Open your AI app.** Claude Desktop, Cursor, Claude Code, Windsurf and Gemini CLI are already connected. Quit and reopen the app, then ask: `Understand this video for me: ~/Desktop/My Video.mp4`.

The plugin lives in `~/.video-context/app` (Windows: `C:\Users\YOURNAME\.video-context\app`). Details for each app are below and on the [help page](https://understandvideo.shipmonthly.com/help.html). An install log is saved at `~/.video-context/install.log`.

*Advanced:* download [video-context-ai.zip](https://github.com/africaappstudio-max/video-context-ai-download/releases/latest/download/video-context-ai.zip) and run `bash install.sh` (Mac) or `install.ps1` (Windows).

**The path the other apps need** (replace YOURNAME with your computer user name):
- Mac: `/Users/YOURNAME/.video-context/app/bin/understand-this-video-mcp`
- Windows: `C:\Users\YOURNAME\.video-context\app\Scripts\understand-this-video-mcp.exe`

### Claude Desktop
1. Run the installer above (it registers Claude Desktop for you).
2. Fully quit Claude Desktop (Mac: Cmd+Q; Windows: right-click its icon in the tray, Quit) and open it again.
3. Start a new chat and type: `Understand this video for me: ~/Desktop/My Video.mp4`. If Claude asks permission to use the plugin, click **Allow**.

**How to check it works:** open **Settings, Developer**. "Understand This Video" should show as *running*. In chat, Claude answers using frames and quotes with times like `[00:21]`.

### Cursor
1. Run the installer above (it registers Cursor for you). Restart Cursor.
2. Open **Cursor Settings** (Mac: Cmd+Shift+J; Windows: Ctrl+Shift+J), click **Tools & MCP** (or **MCP**).
3. To add it by hand instead, open the file `~/.cursor/mcp.json` (Windows: `C:\Users\YOURNAME\.cursor\mcp.json`) and paste this, using your path from above:
```json
{
  "mcpServers": {
    "Understand This Video": {
      "command": "/Users/YOURNAME/.video-context/app/bin/understand-this-video-mcp",
      "args": []
    }
  }
}
```

**How to check it works:** in Cursor Settings, "Understand This Video" has a green dot. In the Agent chat type `Understand this video for me: /path/to/video.mp4`.

### Claude Code
1. Run the installer above.
2. Open Terminal (Windows: PowerShell) and paste one line.
   - Mac: `claude mcp add understand-this-video -- ~/.video-context/app/bin/understand-this-video-mcp`
   - Windows: `claude mcp add understand-this-video -- "$env:USERPROFILE\.video-context\app\Scripts\understand-this-video-mcp.exe"`
3. Start `claude` and ask: `Understand this video for me: ~/Desktop/video.mp4`.

**How to check it works:** type `claude mcp list`. You should see `understand-this-video` marked **Connected**.

### Grok Bot
Grok Bot works on its own cloud computer, so it can't use a program on your laptop. You ask the Bot to set the plugin up on *its* computer. It then works on video files you give the Bot (not on files that stay on your laptop, and not on video website links).
1. Open a chat with your Bot.
2. Send this message:
   > Please install the Understand This Video plugin on your own computer: download https://github.com/africaappstudio-max/video-context-ai-download/releases/latest/download/video-context-ai.zip, unzip it, install ffmpeg if it's missing, then run `pip install .` from the unzipped folder. Then add a command (stdio) MCP server named "Understand This Video" with the command `understand-this-video-mcp`. Ask me for my license key with a secure secret request (never in chat or in the command), then run `understand-this-video activate` with it.
3. When the Bot asks for the key, enter it in the secure box it shows.

**How to check it works:** ask the Bot "Which tools does Understand This Video have?" It should name `understand_this_video`. Then give it a video file and ask what happens in it.

*Grok Build (command line):* `grok mcp add understand-this-video -- ~/.video-context/app/bin/understand-this-video-mcp`

### Windsurf, VS Code, LM Studio, Cline
Run the installer first. Then open your app's MCP settings file and paste the same block as in the Cursor section (with your path):
- **Windsurf:** click the MCP icon in the Cascade panel, then **Configure**. The file is `~/.codeium/windsurf/mcp_config.json`.
- **LM Studio:** open the **Program** tab on the right, click **Install**, then **Edit mcp.json**.
- **Cline:** click the **MCP Servers** icon, then **Configure MCP Servers**.
- **VS Code (Copilot):** press Cmd/Ctrl+Shift+P, run **MCP: Open User Configuration**, and paste this instead (VS Code uses the word `servers`):
```json
{
  "servers": {
    "Understand This Video": {
      "type": "stdio",
      "command": "/Users/YOURNAME/.video-context/app/bin/understand-this-video-mcp",
      "args": []
    }
  }
}
```

**How to check it works:** the server shows as running or connected in that app's MCP list, and the app lists the tool `understand_this_video`.

### If something goes wrong
- *"License error"*: run `understand-this-video activate YOUR-KEY` (Mac: `~/.video-context/app/bin/understand-this-video activate YOUR-KEY`).
- *"ffmpeg not found"*: Mac: `brew install ffmpeg`. Windows: `winget install ffmpeg`. Then restart the app.
- *A video link is rejected*: this plugin only processes video files on your computer. Download or export the video first, then give the AI the file path.
- Still stuck? Email video@shipmonthly.com.

## Example prompts
1. *"Watch ~/Downloads/demo.mp4 and write the step-by-step instructions it shows."*
2. *"Summarize this video with timestamps: ~/Desktop/talk.mp4"*
3. *"Look at this screen recording of my bug, ~/Desktop/bug.mov, and tell me what went wrong."*

## Tool
`understand_this_video`: input `source` (a local file path) plus optional options. Returns the frames as images, the transcript and the timeline. URLs are not accepted.

**Token-friendly defaults (v1.2.0):** up to 12 key frames, 512 px on the longest side, moderate JPEG quality. Raise them with `max_frames` and `max_side` when you need more detail.
**Transcript-only mode:** set `transcript_only: true` (CLI: `--transcript-only`) for the speech transcript with no frames or images. It is the cheapest option for talks, calls and lectures.

## Privacy
Videos are processed locally. The plugin does not download videos from the internet. The only network call is the license check with Freemius (and a one-time download of the free Whisper speech model). See [PRIVACY.md](PRIVACY.md).

## Support
video@shipmonthly.com

Proprietary software © 2026 Ship Monthly. The source is visible, but use needs a paid license. See [LICENSE](LICENSE).
