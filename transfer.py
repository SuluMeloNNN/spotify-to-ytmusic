import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from urllib.request import urlopen

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from ytmusicapi import YTMusic

load_dotenv()

SPOTIFY_SCOPES = "playlist-read-private playlist-read-collaborative"
YTMUSIC_AUTH_FILE = "browser.json"
DEFAULT_BATCH_SIZE = 10
DEFAULT_SEARCH_DELAY = 0.10
DEFAULT_ADD_DELAY = 0.15
REPORTS_DIR = "reports"
COVERS_DIR = "covers"


def ensure_dirs() -> None:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(COVERS_DIR, exist_ok=True)


def get_spotify_client() -> spotipy.Spotify:
    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=os.getenv("SPOTIPY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
            redirect_uri=os.getenv("SPOTIPY_REDIRECT_URI"),
            scope=SPOTIFY_SCOPES,
            open_browser=True,
        )
    )


def get_all_playlists(sp: spotipy.Spotify) -> List[Dict]:
    playlists: List[Dict] = []
    results = sp.current_user_playlists(limit=50)
    playlists.extend(results.get("items", []))

    while results.get("next"):
        results = sp.next(results)
        playlists.extend(results.get("items", []))

    return playlists


def get_playlist_tracks(sp: spotipy.Spotify, playlist_id: str) -> List[Dict]:
    raw_items: List[Dict] = []

    results = sp.playlist_items(
        playlist_id,
        additional_types=["track"],
        limit=100,
    )
    raw_items.extend(results.get("items", []))

    while results.get("next"):
        results = sp.next(results)
        raw_items.extend(results.get("items", []))

    clean_tracks: List[Dict] = []

    for item in raw_items:
        track = item.get("track") or item.get("item")

        if not track:
            continue
        if track.get("type") != "track":
            continue
        if track.get("is_local"):
            continue

        artists: List[str] = []
        for artist in track.get("artists", []):
            if artist and artist.get("name"):
                artists.append(artist["name"])

        clean_tracks.append(
            {
                "title": track.get("name", ""),
                "artists": artists,
                "isrc": (track.get("external_ids") or {}).get("isrc"),
                "spotify_id": track.get("id"),
                "duration_ms": track.get("duration_ms"),
            }
        )

    return clean_tracks


def normalize(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name or "playlist"


def song_label(track: Dict) -> str:
    artists = ", ".join(track.get("artists", []))
    return f"{track.get('title', '')} - {artists}"


def chunks(lst: List, size: int):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def write_track_list(filename: str, tracks: List[Dict]) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        for track in tracks:
            f.write(song_label(track) + "\n")


def download_cover_if_available(playlist: Dict) -> Optional[str]:
    images = playlist.get("images") or []
    if not images:
        return None

    url = images[0].get("url")
    if not url:
        return None

    safe_name = sanitize_filename(playlist.get("name", "playlist"))
    out_path = os.path.join(COVERS_DIR, f"{safe_name}.jpg")

    try:
        with urlopen(url, timeout=20) as resp, open(out_path, "wb") as f:
            f.write(resp.read())
        return out_path
    except Exception:
        return None


def find_existing_yt_playlist(yt: YTMusic, title: str) -> Optional[Dict]:
    try:
        playlists = yt.get_library_playlists(limit=500)
    except Exception:
        return None

    wanted = normalize(title)
    for playlist in playlists:
        if normalize(playlist.get("title", "")) == wanted:
            return playlist
    return None


def search_track_on_yt(yt: YTMusic, track: Dict) -> Optional[str]:
    title = track["title"]
    artists = track["artists"]
    isrc = track.get("isrc")

    queries: List[Tuple[str, Optional[str]]] = []

    if isrc:
        queries.append((isrc, "songs"))

    if artists:
        queries.append((f"{title} {artists[0]}", "songs"))
        queries.append((f"{artists[0]} {title}", "songs"))

    queries.append((title, "songs"))

    if artists:
        queries.append((f"{title} {' '.join(artists[:2])}", None))

    for query, filt in queries:
        try:
            if filt:
                results = yt.search(query, filter=filt, limit=10)
            else:
                results = yt.search(query, limit=10)

            if results:
                for result in results:
                    video_id = result.get("videoId")
                    if video_id:
                        return video_id
        except Exception as e:
            print(f"  Search error for '{query}': {e}")

    return None


def get_playlist_track_count(yt: YTMusic, playlist_id: str) -> Optional[int]:
    try:
        playlist_data = yt.get_playlist(playlist_id, limit=None)
        tracks = playlist_data.get("tracks", [])
        return len(tracks)
    except Exception as e:
        print(f"Could not read playlist back for verification: {e}")
        return None


def add_songs_with_retry(
    yt: YTMusic,
    playlist_id: str,
    matched_tracks: List[Dict],
    batch_size: int,
    add_delay: float,
    allow_duplicates: bool,
) -> Tuple[List[Dict], List[Dict]]:
    added_tracks: List[Dict] = []
    failed_tracks: List[Dict] = []

    for batch_index, part in enumerate(chunks(matched_tracks, batch_size), start=1):
        video_ids = [track["video_id"] for track in part]

        response = None
        try:
            response = yt.add_playlist_items(
                playlist_id,
                video_ids,
                duplicates=allow_duplicates,
            )
            print(
                f"Batch {batch_index}: attempted {len(part)} tracks. "
                f"Response: {response}"
            )
        except Exception as e:
            print(f"Batch {batch_index}: batch add exception: {e}")

        status = response.get("status") if isinstance(response, dict) else None
        if status == "STATUS_SUCCEEDED":
            added_tracks.extend(part)
            time.sleep(add_delay)
            continue

        print(f"Batch {batch_index}: batch add did not succeed. Retrying individually...")

        for track in part:
            try:
                single_response = yt.add_playlist_items(
                    playlist_id,
                    [track["video_id"]],
                    duplicates=allow_duplicates,
                )
                single_status = (
                    single_response.get("status")
                    if isinstance(single_response, dict)
                    else None
                )

                if single_status == "STATUS_SUCCEEDED":
                    added_tracks.append(track)
                    print(f"  ADDED     {song_label(track)}")
                else:
                    failed_tracks.append(track)
                    print(f"  FAILED    {song_label(track)} | Response: {single_response}")
            except Exception as e:
                failed_tracks.append(track)
                print(f"  FAILED    {song_label(track)} | Error: {e}")

            time.sleep(add_delay)

    return added_tracks, failed_tracks


def build_report(
    source_playlist: Dict,
    yt_playlist_id: Optional[str],
    tracks: List[Dict],
    matched_tracks: List[Dict],
    added_tracks: List[Dict],
    not_found_tracks: List[Dict],
    failed_additions: List[Dict],
    playlist_count: Optional[int],
    cover_path: Optional[str],
    mode: str,
    existing_mode: str,
) -> Dict:
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "existing_mode": existing_mode,
        "source_playlist_name": source_playlist.get("name"),
        "source_playlist_id": source_playlist.get("id"),
        "spotify_total": len(tracks),
        "matched_on_ytmusic": len(matched_tracks),
        "confirmed_added": len(added_tracks),
        "search_not_found": len(not_found_tracks),
        "add_failures": len(failed_additions),
        "yt_playlist_id": yt_playlist_id,
        "playlist_count_read": playlist_count,
        "cover_export_path": cover_path,
        "search_not_found_tracks": [song_label(t) for t in not_found_tracks],
        "add_failed_tracks": [song_label(t) for t in failed_additions],
    }


def save_report(playlist_name: str, report: Dict) -> str:
    safe_name = sanitize_filename(playlist_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORTS_DIR, f"report_{safe_name}_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path


def transfer_one_playlist(
    sp: spotipy.Spotify,
    yt: YTMusic,
    selected_playlist: Dict,
    dry_run: bool,
    existing_mode: str,
    batch_size: int,
    search_delay: float,
    add_delay: float,
    export_cover: bool,
    allow_duplicates: bool,
):
    playlist_name = selected_playlist["name"]
    print(f"\n=== Transferring: {playlist_name} ===")

    cover_path = download_cover_if_available(selected_playlist) if export_cover else None
    if cover_path:
        print(f"Exported Spotify cover: {cover_path}")

    tracks = get_playlist_tracks(sp, selected_playlist["id"])
    print(f"Spotify tracks available for transfer: {len(tracks)}")

    if not tracks:
        print("No transferable tracks found in this playlist.")
        report = build_report(
            source_playlist=selected_playlist,
            yt_playlist_id=None,
            tracks=[],
            matched_tracks=[],
            added_tracks=[],
            not_found_tracks=[],
            failed_additions=[],
            playlist_count=None,
            cover_path=cover_path,
            mode="dry-run" if dry_run else "transfer",
            existing_mode=existing_mode,
        )
        report_path = save_report(playlist_name, report)
        print(f"Saved report: {report_path}")
        return

    matched_tracks: List[Dict] = []
    not_found_tracks: List[Dict] = []

    for i, track in enumerate(tracks, start=1):
        print(f"Searching [{i}/{len(tracks)}]: {song_label(track)}")
        video_id = search_track_on_yt(yt, track)

        if video_id:
            enriched = dict(track)
            enriched["video_id"] = video_id
            matched_tracks.append(enriched)
            print(f"  FOUND     {song_label(track)}")
        else:
            not_found_tracks.append(track)
            print(f"  NOT FOUND {song_label(track)}")

        time.sleep(search_delay)

    print(f"\nSearch summary for '{playlist_name}':")
    print(f"- Spotify tracks:      {len(tracks)}")
    print(f"- Found on YT Music:   {len(matched_tracks)}")
    print(f"- Not found in search: {len(not_found_tracks)}")

    yt_playlist_id: Optional[str] = None
    added_tracks: List[Dict] = []
    failed_additions: List[Dict] = []
    playlist_count: Optional[int] = None

    if dry_run:
        print("Dry-run mode enabled. No YouTube Music playlist will be created or modified.")
    else:
        existing = find_existing_yt_playlist(yt, playlist_name)
        if existing and existing_mode == "skip":
            yt_playlist_id = existing.get("playlistId") or existing.get("browseId")
            print(f"Existing playlist found. Skipping due to --existing skip: {yt_playlist_id}")
        else:
            yt_playlist_id = yt.create_playlist(
                title=playlist_name,
                description="Transferred from Spotify",
                privacy_status="PRIVATE",
            )
            print(f"Created YouTube Music playlist: {yt_playlist_id}")

            added_tracks, failed_additions = add_songs_with_retry(
                yt=yt,
                playlist_id=yt_playlist_id,
                matched_tracks=matched_tracks,
                batch_size=batch_size,
                add_delay=add_delay,
                allow_duplicates=allow_duplicates,
            )
            playlist_count = get_playlist_track_count(yt, yt_playlist_id)

    print("\n=== Final summary ===")
    print(f"Playlist:               {playlist_name}")
    print(f"Spotify total:          {len(tracks)}")
    print(f"Found on YT Music:      {len(matched_tracks)}")
    print(f"Confirmed added:        {len(added_tracks)}")
    print(f"Search not found:       {len(not_found_tracks)}")
    print(f"Add failures:           {len(failed_additions)}")
    print(f"Playlist count (read):  {playlist_count if playlist_count is not None else 'unknown'}")

    safe_name = sanitize_filename(playlist_name)

    if not_found_tracks:
        not_found_file = f"not_found_{safe_name}.txt"
        write_track_list(not_found_file, not_found_tracks)
        print(f"Saved search misses to: {not_found_file}")

    if failed_additions:
        failed_file = f"add_failed_{safe_name}.txt"
        write_track_list(failed_file, failed_additions)
        print(f"Saved add failures to:  {failed_file}")

    report = build_report(
        source_playlist=selected_playlist,
        yt_playlist_id=yt_playlist_id,
        tracks=tracks,
        matched_tracks=matched_tracks,
        added_tracks=added_tracks,
        not_found_tracks=not_found_tracks,
        failed_additions=failed_additions,
        playlist_count=playlist_count,
        cover_path=cover_path,
        mode="dry-run" if dry_run else "transfer",
        existing_mode=existing_mode,
    )
    report_path = save_report(playlist_name, report)
    print(f"Saved report:           {report_path}")



def parse_selection(selection: str, total: int) -> List[int]:
    indexes: List[int] = []
    for part in selection.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < total:
                indexes.append(idx)
    return indexes



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transfer Spotify playlists to YouTube Music."
    )
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", help="List your Spotify playlists")
    list_parser.set_defaults(command="list")

    transfer_parser = subparsers.add_parser("transfer", help="Transfer selected playlists")
    transfer_parser.add_argument(
        "--playlists",
        help="Comma-separated playlist numbers from the list command, e.g. 1,3,5",
    )
    transfer_parser.add_argument(
        "--existing",
        choices=["create-new", "skip"],
        default="create-new",
        help="What to do if a YouTube Music playlist with the same title already exists.",
    )
    transfer_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    transfer_parser.add_argument("--search-delay", type=float, default=DEFAULT_SEARCH_DELAY)
    transfer_parser.add_argument("--add-delay", type=float, default=DEFAULT_ADD_DELAY)
    transfer_parser.add_argument(
        "--export-cover",
        action="store_true",
        help="Export Spotify playlist cover image locally.",
    )
    transfer_parser.add_argument(
        "--no-duplicates",
        action="store_true",
        help="Ask YouTube Music not to add duplicates.",
    )
    transfer_parser.set_defaults(command="transfer", dry_run=False)

    dry_run_parser = subparsers.add_parser("dry-run", help="Search only, do not create playlists")
    dry_run_parser.add_argument(
        "--playlists",
        help="Comma-separated playlist numbers from the list command, e.g. 1,3,5",
    )
    dry_run_parser.add_argument("--search-delay", type=float, default=DEFAULT_SEARCH_DELAY)
    dry_run_parser.add_argument(
        "--export-cover",
        action="store_true",
        help="Export Spotify playlist cover image locally.",
    )
    dry_run_parser.set_defaults(command="dry-run", dry_run=True)

    return parser



def main() -> None:
    ensure_dirs()
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command in {"transfer", "dry-run"} and not os.path.exists(YTMUSIC_AUTH_FILE):
        print(f"Missing auth file: {YTMUSIC_AUTH_FILE}")
        return

    sp = get_spotify_client()
    playlists = get_all_playlists(sp)

    if not playlists:
        print("No Spotify playlists found.")
        return

    if args.command == "list":
        print("\nYour Spotify playlists:\n")
        for i, playlist in enumerate(playlists, start=1):
            print(f"{i}. {playlist['name']}")
        return

    yt = YTMusic(YTMUSIC_AUTH_FILE)

    print("\nYour Spotify playlists:\n")
    for i, playlist in enumerate(playlists, start=1):
        print(f"{i}. {playlist['name']}")

    selection = getattr(args, "playlists", None)
    if not selection:
        selection = input("\nEnter playlist numbers to process (example: 1,3,5): ").strip()

    indexes = parse_selection(selection, len(playlists))
    if not indexes:
        print("No valid playlist selection provided.")
        return

    selected_playlists = [playlists[i] for i in indexes]

    for playlist in selected_playlists:
        try:
            transfer_one_playlist(
                sp=sp,
                yt=yt,
                selected_playlist=playlist,
                dry_run=args.dry_run,
                existing_mode=getattr(args, "existing", "create-new"),
                batch_size=getattr(args, "batch_size", DEFAULT_BATCH_SIZE),
                search_delay=getattr(args, "search_delay", DEFAULT_SEARCH_DELAY),
                add_delay=getattr(args, "add_delay", DEFAULT_ADD_DELAY),
                export_cover=getattr(args, "export_cover", False),
                allow_duplicates=not getattr(args, "no_duplicates", False),
            )
        except Exception as e:
            print(f"\nERROR while processing '{playlist['name']}': {e}")


if __name__ == "__main__":
    main()
