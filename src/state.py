
def create_server_state():
    return {
        "current_video": None,
        "is_paused": True,
        "current_time": 0,
        "host_sid": None,
        "users": {},
        "is_screen_sharing": False,
        "screen_share_session_id": None,
        "rtc_mode": "auto",
    }


server_state = create_server_state()
