
def create_server_state():
    try:
        from config import ALLOW_REMOTE_HOST_ADMIN
    except ImportError:
        ALLOW_REMOTE_HOST_ADMIN = False
    return {
        "current_video": None,
        "is_paused": True,
        "current_time": 0,
        "host_sid": None,
        "users": {},
        "is_screen_sharing": False,
        "screen_share_session_id": None,
        "rtc_mode": "auto",
        "allow_remote_host_admin": ALLOW_REMOTE_HOST_ADMIN,
        "current_media_snapshot": None,
        "history_last_checkpoint_position": None,
        "history_last_checkpoint_monotonic": None,
    }


server_state = create_server_state()

from host_store import HostStore

host_store = HostStore("cache/watchparty.sqlite3")
