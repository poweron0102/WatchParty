import requests



def get_public_ip():
    """Tenta descobrir o IP público, priorizando IPv6."""
    try:
        response = requests.get('https://api64.ipify.org', timeout=3)
        if response.status_code == 200:
            return response.text
    except requests.RequestException:
        pass

    try:
        response = requests.get('https://icanhazip.com', timeout=3)
        if response.status_code == 200:
            return response.text
    except requests.RequestException:
        return "127.0.0.1"

    return "127.0.0.1"
