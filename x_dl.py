#!/usr/bin/env python3
import argparse
import os
import re
import requests
import random
import time
import json
from datetime import datetime
import gallery_dl
from gallery_dl.extractor import twitter
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

CHECKPOINT_DIR = ".checkpoints"

def setup_gallery_dl(auth_token=None):
    """Configure gallery-dl with authentication if provided."""
    config = gallery_dl.config._config
    if "extractor" not in config:
        config["extractor"] = {}
    if "twitter" not in config["extractor"]:
        config["extractor"]["twitter"] = {}
    config["extractor"]["twitter"].update({
        "api": "gallery-dl",
        "videos": True,
        "retweets": False,
        "replies": False
    })
    if auth_token:
        if "cookies" not in config["extractor"]["twitter"]:
             config["extractor"]["twitter"]["cookies"] = {}
        config["extractor"]["twitter"]["cookies"]["auth_token"] = auth_token

def get_auth_token(auth_token_arg=None):
    """Get auth token from command line argument or .env file."""
    if auth_token_arg:
        return auth_token_arg
    load_dotenv()
    return os.getenv('AUTH_TOKEN')

def create_session():
    """Create a basic requests session without retry mechanism."""
    session = requests.Session()
    return session

def fetch_media_metadata(username, auth_token, content_type="media", limit=0, last_downloaded_id=None, redownload=False):
    """Fetches the latest 'limit' media metadata items for a user, stopping early if checkpoint is reached."""
    url = f"https://x.com/{username}/{content_type}"
    
    if content_type == "media":
        selected_extractor = twitter.TwitterMediaExtractor
    elif content_type == "tweets":
        selected_extractor = twitter.TwitterTweetsExtractor
    elif content_type == "with_replies":
        selected_extractor = twitter.TwitterRepliesExtractor
    else:
        selected_extractor = twitter.TwitterTimelineExtractor
    
    match = re.match(selected_extractor.pattern, url)
    if not match:
        print(f"Error: Invalid URL for {content_type}: {url}")
        return None

    try:
        extractor = selected_extractor(match)
    except Exception as e:
        print(f"Failed to initialize extractor for @{username}: {e}")
        return None

    config_dict = { "cookies": { "auth_token": auth_token } }
    extractor.config = lambda key, default=None: config_dict.get(key, default)

    try:
        extractor.initialize()
        api = twitter.TwitterAPI(extractor)
        
        try: # User validation
            if username.startswith("id:"):
                user = api.user_by_rest_id(username[3:])
            else:
                user = api.user_by_screen_name(username)
            if "legacy" in user and user["legacy"].get("withheld_scope"):
                print(f"Error: Account @{username} is withheld")
                return None
        except Exception as e:
            error_msg = str(e).lower()
            if "withheld" in error_msg or (hasattr(e, "response") and "withheld" in str(e.response.text).lower()):
                print(f"Error: Account @{username} is withheld")
            else:
                print(f"Error validating user @{username}: {e}")
            return None

        structured_output = {'account_info': {}, 'total_urls': 0, 'timeline': []}
        iterator = iter(extractor)
        items_to_fetch = limit if limit > 0 else float('inf')
        items_fetched = 0
        checkpoint_reached = False
        last_id_int = None
        
        # Only use checkpoint if not redownloading
        if not redownload and last_downloaded_id:
            try: last_id_int = int(last_downloaded_id)
            except (ValueError, TypeError): last_downloaded_id = None

        try: # Main fetching loop
            while items_fetched < items_to_fetch:
                item = next(iterator)
                items_fetched += 1
                if isinstance(item, tuple) and len(item) >= 3:
                    media_url, tweet_data = item[1], item[2]
                    current_tweet_id = tweet_data.get('tweet_id')

                    # Skip this item if it's older than or equal to the checkpoint (and not redownloading)
                    if not redownload and last_id_int is not None and current_tweet_id:
                        try:
                            if int(current_tweet_id) <= last_id_int:
                                checkpoint_reached = True
                                continue  # Skip this item
                        except (ValueError, TypeError): pass

                    # Extract account info (once)
                    if not structured_output['account_info'] and 'user' in tweet_data:
                        user_data = tweet_data['user']
                        user_date_str = user_data.get('date', '')
                        if isinstance(user_date_str, datetime): user_date_str = user_date_str.strftime("%Y-%m-%d %H:%M:%S")
                        structured_output['account_info'] = {
                            'name': user_data.get('name', ''), 'nick': user_data.get('nick', ''), 'date': user_date_str,
                            'followers_count': user_data.get('followers_count', 0), 'friends_count': user_data.get('friends_count', 0),
                            'profile_image': user_data.get('profile_image', ''), 'statuses_count': user_data.get('statuses_count', 0)
                        }

                    # Process media item
                    if 'pbs.twimg.com' in media_url or 'video.twimg.com' in media_url:
                        timeline_entry = {
                            'url': media_url, 'date': tweet_data.get('date', datetime.now()),
                            'tweet_id': current_tweet_id,
                        }
                        if 'type' in tweet_data: timeline_entry['type'] = tweet_data['type']
                        structured_output['timeline'].append(timeline_entry)
                        structured_output['total_urls'] += 1

                if checkpoint_reached:
                    print(f"Checkpoint reached (Tweet ID {current_tweet_id} <= {last_id_int}). Stopping metadata fetch.")
                    break

        except StopIteration: pass # End of timeline

        # --- Metadata ---
        cursor_info = getattr(extractor, '_cursor', None)
        stopped_by_limit = limit > 0 and items_fetched >= limit
        has_more = stopped_by_limit or checkpoint_reached
        structured_output['metadata'] = {
            "fetched_entries": items_fetched, "media_entries": len(structured_output['timeline']),
            "limit": limit, "checkpoint_reached": checkpoint_reached, "has_more": has_more, "cursor": cursor_info
        }

        if not structured_output['account_info'] and not structured_output['timeline']:
            print("Warning: No media or account information found during fetch.")
            if limit > 0 and items_fetched == 0: print(f"Could not fetch any posts for @{username} (within limit {limit}).")
            if checkpoint_reached and not structured_output['timeline']: print("No new media found since last checkpoint.")
        return structured_output

    except Exception as e:
        print(f"Error fetching data for @{username}: {str(e)}")
        return None

def filter_media_by_date(metadata_list, start_date_str):
    """Filters a list of media metadata by start date."""
    if not start_date_str: return metadata_list
    try:
        start_datetime = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=None)
    except ValueError:
        print(f"Invalid date format: {start_date_str}. Please use YYYY-MM-DD format.")
        return []
    return [item for item in metadata_list
            if isinstance(item.get('date'), datetime) and item['date'].replace(tzinfo=None) >= start_datetime]

# --- Checkpoint Functions ---
def get_checkpoint_filepath(username):
    """Returns the expected path for a user's checkpoint file."""
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    safe_username = username.replace('/', '_').replace('\\', '_')
    return os.path.join(CHECKPOINT_DIR, f"{safe_username}.json")

def load_checkpoint(username):
    """Loads the last_downloaded_id from the checkpoint file for a specific user."""
    filepath = get_checkpoint_filepath(username)
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
            # Primarily return the ID for existing logic
            return data.get('last_downloaded_id') 
    except (json.JSONDecodeError, KeyError, Exception) as e:
        print(f"Warning: Could not read/parse checkpoint file {filepath} (Error: {e}). Treating as no checkpoint.")
        # Optionally, attempt to delete or rename the corrupt file here
        return None

def save_checkpoint(username, last_downloaded_id, last_downloaded_date=None):
    """Saves the checkpoint data (ID, date, timestamp) for a specific user."""
    filepath = get_checkpoint_filepath(username)
    # Ensure date is in a serializable format (ISO 8601 string)
    date_str = last_downloaded_date.isoformat() if isinstance(last_downloaded_date, datetime) else None
    data = {
        'last_downloaded_id': str(last_downloaded_id),
        'last_downloaded_date': date_str,
        'last_updated_timestamp': datetime.now().isoformat()
    }
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Warning: Could not write to checkpoint file {filepath}: {e}")

# --- Preview Function ---
def preview_media(username, start_date=None, auth_token=None, limit=0, redownload=False):
    """Preview media URLs from a specific X.com user without downloading, respecting checkpoints."""
    auth_token = get_auth_token(auth_token)
    
    # Load checkpoint using the new function
    last_downloaded_id = load_checkpoint(username)
    
    print(f"Fetching metadata for @{username}" + (f" (limit: {limit})" if limit > 0 else "") + "...")
    if last_downloaded_id and not redownload:
        print(f"Checkpoint found: Previewing media newer than Tweet ID {last_downloaded_id}")
    elif redownload:
        print("Redownload mode: Previewing all media (ignoring checkpoint)")

    result = fetch_media_metadata(username, auth_token, limit=limit, last_downloaded_id=last_downloaded_id, redownload=redownload)
    if result is None: print("Failed to fetch metadata."); return
    
    timeline_data = result['timeline']
    print(f"Filtering preview results from date {start_date}...")
    filtered_metadata = filter_media_by_date(timeline_data, start_date)
    
    fetch_info = result['metadata']
    examined_count = fetch_info['fetched_entries']
    checkpoint_info = f" (stopped at checkpoint {last_downloaded_id})" if fetch_info['checkpoint_reached'] and not redownload else ""
    limit_info = f" (within the last {examined_count} posts examined{checkpoint_info})" if limit > 0 or fetch_info['checkpoint_reached'] else ""
    redownload_info = " (including all media, ignoring checkpoint)" if redownload else ""
    print(f"\nFound {len(filtered_metadata)} media items to preview for @{username}" + (f" since {start_date}" if start_date else "") + limit_info + redownload_info + ":")
    print("-" * 50)
    if not filtered_metadata: print("No media found matching the criteria.")
    else:
        for item in filtered_metadata:
            if 'url' in item: print(item['url'])
    print("-" * 50)
    print("This was a preview. Use without --preview to download the media.")

# --- Download Functions ---
def download_file(session, item, output_dir, index, total, allow_redownload=False, last_downloaded_id=None, min_size_kb=128):
    """Download a single file with proper error handling, respecting redownload flag, checkpoint, and minimum size."""
    url = item.get('url')
    if not url: return "", False, "Missing URL"

    try:
        # --- Filename Construction ---
        date_obj = item.get('date'); id_part = item.get('tweet_id', 'unknown_id'); num_part = index
        date_part = date_obj.strftime('%Y-%m-%d') if isinstance(date_obj, datetime) else datetime.now().strftime('%Y-%m-%d')
        ext_part = 'unknown'
        if url:
            try:
                url_path = url.split('?')[0]; base_ext = url_path.split('.')[-1]
                if len(base_ext) <= 5 and '/' not in base_ext: ext_part = base_ext
            except IndexError: pass
        if ext_part == 'unknown':
            media_type = item.get('type')
            if media_type == 'video' or media_type == 'animated_gif': ext_part = 'mp4'
            elif media_type == 'photo': ext_part = 'jpg'
        id_str = str(id_part); filename = f"{date_part}_{id_str}_{num_part}.{ext_part}"
        filepath = os.path.join(output_dir, filename)
        # --- End Filename Construction ---

        # Check if file exists
        file_exists = os.path.exists(filepath)
        
        # Check if tweet is older than checkpoint
        tweet_id = item.get('tweet_id')
        is_older_than_checkpoint = False
        if last_downloaded_id and tweet_id:
            try:
                tweet_id_int = int(tweet_id)
                last_id_int = int(last_downloaded_id)
                is_older_than_checkpoint = tweet_id_int <= last_id_int
            except (ValueError, TypeError):
                pass

        # Skip if tweet is older than checkpoint and we're not forcing redownload
        if is_older_than_checkpoint and not allow_redownload:
            print(f"Skipping ({index + 1}/{total}): {url} (older than checkpoint)")
            return filename, True, "Tweet older than checkpoint"
        
        # Skip if file exists and we're not allowing redownload
        if file_exists and not allow_redownload:
            print(f"Skipping ({index + 1}/{total}): {url} (already exists)")
            return filename, True, "File already exists"

        # --- Check File Size (if min_size_kb > 0) ---
        if min_size_kb > 0:
            min_size_bytes = min_size_kb * 1024
            try:
                head_response = session.head(url, allow_redirects=True, timeout=(5, 5))
                head_response.raise_for_status()
                content_length_str = head_response.headers.get('content-length')
                
                if content_length_str:
                    try:
                        content_length = int(content_length_str)
                        if content_length < min_size_bytes:
                            print(f"Skipping ({index + 1}/{total}): {url} (size {content_length} bytes < {min_size_kb}KB)")
                            return filename, True, f"File too small (<{min_size_kb}KB)"
                    except ValueError:
                        print(f"Warning ({index + 1}/{total}): Could not parse Content-Length '{content_length_str}' for {url}. Proceeding.")
                # else: Content-Length header missing, proceed.
                    
            except requests.exceptions.RequestException as head_err:
                print(f"Warning ({index + 1}/{total}): HEAD request failed for {url} ({head_err}). Proceeding.")
            except Exception as head_err:
                 print(f"Warning ({index + 1}/{total}): Error during HEAD request for {url} ({head_err}). Proceeding.")
        # --- End File Size Check ---
            
        # If we get here, we should download the file
        print(f"Downloading ({index + 1}/{total}): {url}")
        response = session.get(url, stream=True, timeout=(5, 10))
        response.raise_for_status()
        chunk_size = 4096
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk: f.write(chunk)
        return filename, True, ""

    except requests.exceptions.RequestException as e:
        error_msg = f"Failed to download {url}: {str(e)}"
        print(f"\nError: {error_msg}")
        return "", False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error downloading {url}: {str(e)}"
        print(f"\nError: {error_msg}")
        return "", False, error_msg

def download_media(username, output_dir, start_date=None, auth_token=None, limit=0, redownload=False, min_size_kb=128):
    """Download media from a specific X.com user into a user-specific subfolder, using checkpoints."""
    os.makedirs(output_dir, exist_ok=True)
    user_output_dir = os.path.join(output_dir, username)
    os.makedirs(user_output_dir, exist_ok=True)
    last_downloaded_id = load_checkpoint(username)
    auth_token = get_auth_token(auth_token)
    print(f"Fetching metadata for @{username}" + (f" (limit: {limit})" if limit > 0 else "") + "...")
    if last_downloaded_id and not redownload: 
        print(f"Checkpoint found: Will fetch media newer than Tweet ID {last_downloaded_id}")
    elif redownload:
        print("Redownload mode: Will fetch all media (ignoring checkpoint)")

    result = fetch_media_metadata(username, auth_token, limit=limit, last_downloaded_id=last_downloaded_id, redownload=redownload)
    if result is None: print("Failed to fetch metadata."); return
    timeline_data = result['timeline']
    print(f"Filtering {len(timeline_data)} fetched items by date ({start_date or 'No date limit'})...")
    filtered_metadata = filter_media_by_date(timeline_data, start_date)
    if not filtered_metadata:
        print("No new media found matching the criteria (after date filter) to download.")
        if result['metadata']['checkpoint_reached'] and not timeline_data: print("(Fetching stopped early due to checkpoint).")
        return
    total_files = len(filtered_metadata)
    fetch_info = result['metadata']; examined_count = fetch_info['fetched_entries']
    checkpoint_info = f" (stopped at checkpoint {last_downloaded_id})" if fetch_info['checkpoint_reached'] and not redownload else ""
    examined_info = f" (filtered from {examined_count} posts examined{checkpoint_info})" if examined_count > total_files else ""
    redownload_msg = " (redownload mode: ignoring checkpoint and attempting to overwrite existing files)" if redownload else ""
    print(f"Starting download of {total_files} media items to {user_output_dir}{examined_info}{redownload_msg}...")

    downloaded_count, skipped_count, failed_count, older_than_checkpoint_count = 0, 0, 0, 0
    new_highest_id = 0
    new_highest_id_date = None  # Track date associated with the highest ID
    size_skip_count = 0 # Track skips due to size
    session = create_session()
    try:
        # Set max_workers to 1 for single simultaneous download
        with ThreadPoolExecutor(max_workers=1) as executor:
            # Ensure all arguments are passed correctly to download_file
            future_to_item = { 
                executor.submit(
                    download_file, 
                    session, 
                    item, 
                    user_output_dir, # Ensure this is passed correctly
                    i, 
                    total_files, 
                    redownload, 
                    last_downloaded_id,
                    min_size_kb 
                ): item
                for i, item in enumerate(filtered_metadata) 
            }
            processed_count = 0
            for future in as_completed(future_to_item):
                processed_count += 1
                item = future_to_item[future]; skip_occurred = False
                try:
                    filename, success, error_msg = future.result()
                    if success:
                        if error_msg == "File already exists":
                            skipped_count += 1; skip_occurred = True
                        elif error_msg == "Tweet older than checkpoint":
                            older_than_checkpoint_count += 1; skip_occurred = True
                        elif error_msg and error_msg.startswith("File too small"):
                            size_skip_count += 1; skip_occurred = True
                        else: # Successful download (new or redownloaded)
                            downloaded_count += 1
                            tweet_id = item.get('tweet_id')
                            tweet_date = item.get('date') # Get the date of the tweet
                            if isinstance(tweet_id, (int, str)) and tweet_id:
                                try: 
                                    current_id_int = int(tweet_id)
                                    if current_id_int > new_highest_id:
                                        new_highest_id = current_id_int
                                        new_highest_id_date = tweet_date # Store the date
                                except (ValueError, TypeError): pass
                    else: failed_count += 1
                except Exception as e:
                    print(f"\nError processing download result for {item.get('url', 'unknown URL')}: {str(e)}")
                    failed_count += 1
    except KeyboardInterrupt: print("\nDownload interrupted by user.")
    except Exception as e: print(f"\nError during download process: {str(e)}")
    finally:
        session.close()
        print() # Clear status line

    # --- Update Checkpoint ---
    # Determine the ID and Date to save
    final_id_to_save = last_downloaded_id
    final_date_to_save = None # We don't easily have the old date, so default to None if no update

    if new_highest_id > 0:
        needs_update = False
        current_checkpoint_id_int = None
        if last_downloaded_id:
            try:
                current_checkpoint_id_int = int(last_downloaded_id)
            except (ValueError, TypeError):
                print(f"Warning: Invalid format for current checkpoint ID {last_downloaded_id}.")
        
        if current_checkpoint_id_int is None or new_highest_id > current_checkpoint_id_int:
            needs_update = True
            final_id_to_save = new_highest_id
            final_date_to_save = new_highest_id_date
            print(f"Updating checkpoint for @{username} to Tweet ID: {new_highest_id}")
        elif downloaded_count > 0:
            # Keep the old ID, but acknowledge we checked
            print(f"No update to checkpoint ID needed (current: {last_downloaded_id}, highest downloaded this run: {new_highest_id}). Updating timestamp.")
        # If needs_update is False and downloaded_count is 0, we still save below
            
    elif downloaded_count > 0:
         print("Warning: Files were downloaded, but could not determine a new checkpoint ID. Saving checkpoint with old ID if available.")
    elif skipped_count > 0 or older_than_checkpoint_count > 0:
        print(f"No new files downloaded. Updating checkpoint timestamp for @{username}.")
    
    # Always save the checkpoint file to update the timestamp, using the determined ID/Date
    if final_id_to_save is not None:
      save_checkpoint(username, final_id_to_save, final_date_to_save)
    else:
      # If there was no previous checkpoint and no new files downloaded, 
      # we can't save an ID. We could save an empty checkpoint or just skip.
      # Let's skip saving if there's absolutely nothing to save.
      if downloaded_count == 0 and skipped_count == 0 and older_than_checkpoint_count == 0:
         print(f"No media found or downloaded for @{username}, and no previous checkpoint. Skipping checkpoint save.")
      else: 
         # Save with null ID if no previous and nothing new downloaded, but files were processed/skipped
         save_checkpoint(username, None, None) 

    # --- Summary ---
    print("-" * 50); print("Download Summary:")
    print(f"  Successfully downloaded: {downloaded_count}")
    print(f"  Skipped (already exist): {skipped_count}")
    if size_skip_count > 0:
        print(f"  Skipped (too small): {size_skip_count}")
    if older_than_checkpoint_count > 0 and not redownload:
        print(f"  Skipped (older than checkpoint): {older_than_checkpoint_count}")
    print(f"  Failed: {failed_count}")
    print(f"  Total media matching criteria: {total_files}")
    if examined_info: print(f"  {examined_info.strip()}")
    elif limit > 0: print(f"  (Examined up to {limit} posts)")
    print(f"Files saved to: {user_output_dir}"); print("-" * 50)

# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(description="Download media from X.com user")
    parser.add_argument("username", help="X.com username (without @)")
    parser.add_argument("--output", "-o", default="./downloads", help="Output directory")
    parser.add_argument("--date", "-d", help="Start date YYYY-MM-DD")
    parser.add_argument("--auth-token", help="X.com auth token")
    parser.add_argument("--preview", "-p", action="store_true", help="Preview URLs only")
    parser.add_argument("--timeline", "-t", default="media", choices=["media", "tweets", "with_replies"], help="Timeline type")
    parser.add_argument("--limit", "-l", type=int, default=0, help="Limit N most recent posts (0=all)")
    parser.add_argument("--redownload", action="store_true", help="Ignore checkpoint for fetching and attempt to redownload all files")
    parser.add_argument("--min-size-kb", type=int, default=128, help="Minimum file size in KB to download (0 to disable size check)")
    args = parser.parse_args()
    try:
        if args.preview:
            preview_media(args.username, args.date, args.auth_token, args.limit, args.redownload)
        else:
            download_media(args.username, args.output, args.date, args.auth_token, args.limit, args.redownload, args.min_size_kb)
    except KeyboardInterrupt: print("\nOperation cancelled by user."); return 1
    except Exception as e: print(f"An error occurred: {str(e)}"); return 1
    return 0

if __name__ == "__main__":
    exit(main())
