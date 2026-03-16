# spotify-to-ytmusic

Transfer Spotify playlists to YouTube Music with retry logic, failure reports, dry-run support, and search diagnostics.

This tool helps you migrate playlists from Spotify to YouTube Music while providing detailed feedback about what was matched, added, skipped, or failed.

---

## Features

- Transfer one or multiple Spotify playlists to YouTube Music
- Search diagnostics for every track
- Retry failed add operations individually
- Save `not found` and `add failed` text reports
- Save JSON reports for every processed playlist
- Dry-run mode for search-only testing
- Optional Spotify playlist cover export
- Skip existing YouTube Music playlists by title

---

## Important note

This project uses:

- **Spotify Web API** to read Spotify playlists
- **ytmusicapi** to interact with YouTube Music

`ytmusicapi` is **not an official Google API**.

Because of that, behavior may occasionally change if YouTube Music changes its web interface or session behavior.

---

## Requirements

- Python **3.10+**
- A **Spotify developer application**
- A valid **browser.json** file for YouTube Music authentication

---

## Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/spotify-to-ytmusic.git
cd spotify-to-ytmusic
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Project structure

```text
spotify-to-ytmusic/
├── transfer.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
├── LICENSE
├── reports/
└── covers/
```

---

## Setup

### 1. Spotify credentials

Copy `.env.example` and rename it to `.env`.

Fill it with your Spotify developer credentials:

```env
SPOTIPY_CLIENT_ID=your_spotify_client_id
SPOTIPY_CLIENT_SECRET=your_spotify_client_secret
SPOTIPY_REDIRECT_URI=http://127.0.0.1:8080/callback
```

Create a Spotify application here:

`https://developer.spotify.com/dashboard`

Add this redirect URI in your Spotify app settings:

```text
http://127.0.0.1:8080/callback
```

---

### 2. YouTube Music authentication

Place a valid `browser.json` file in the project root:

```text
spotify-to-ytmusic/browser.json
```

This file contains authentication headers extracted from a logged-in YouTube Music session.

---

## Quick start

Typical workflow:

### 1) List your Spotify playlists

```bash
python transfer.py list
```

Example output:

```text
1. Gym
2. Roadtrip
3. PhonkloNNN
4. Coding Music
```

Each playlist is assigned a number.

You will use these numbers when running transfer commands.

---

### 2) Test the search with dry-run

This searches YouTube Music but does not create playlists.

```bash
python transfer.py dry-run --playlists 3
```

Example output:

```text
Searching [1/41]: TECHNO KILLA - KUTE
  FOUND     TECHNO KILLA - KUTE
```

This is useful to verify match quality before transferring.

---

### 3) Transfer the playlist

```bash
python transfer.py transfer --playlists 3
```

Multiple playlists:

```bash
python transfer.py transfer --playlists 1,3,5
```

---

## Optional flags

### Skip existing YouTube Music playlists

```bash
python transfer.py transfer --playlists 1,2 --existing skip
```

### Export Spotify playlist covers locally

```bash
python transfer.py transfer --playlists 1 --export-cover
```

Saved to:

```text
covers/
```

### Disable duplicate adds

```bash
python transfer.py transfer --playlists 1 --no-duplicates
```

---

## Output files

The tool generates useful diagnostic files.

### Text reports

Tracks that cannot be found in search:

```text
not_found_<playlist_name>.txt
```

Tracks that are found but fail during add operations:

```text
add_failed_<playlist_name>.txt
```

### JSON reports

Each playlist transfer generates a JSON report in the `reports/` directory.

Example:

```json
{
  "source_playlist_name": "PhonkloNNN",
  "spotify_total": 41,
  "matched_on_ytmusic": 41,
  "confirmed_added": 41,
  "search_not_found": 0,
  "add_failures": 0,
  "yt_playlist_id": "PL..."
}
```

This helps debug mismatches or transfer issues.

---

## Security notes

Never commit these files to GitHub:

```text
.env
browser.json
headers_auth.json
```

They may contain authentication tokens or session data.

---

## Known limitations

- Matching is based on search heuristics and may not always pick the exact version of a track
- Very large playlists may require retries
- Playlist cover upload to YouTube Music is not implemented
- Since `ytmusicapi` is unofficial, future YouTube changes may affect behavior

---

## License

MIT

---

## Support the project

If this tool helped you migrate your playlists, consider starring the repository.
