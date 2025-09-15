import json
from datetime import datetime
from colorama import init, Fore, Style

init(autoreset=True)

def logger(message, level='info', data=None):
    color_map = {
        'info': Fore.CYAN,
        'debug': Fore.WHITE,
        'error': Fore.RED,
        'success': Fore.GREEN,
        'warn': Fore.YELLOW
    }
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"{Style.BRIGHT}[{timestamp}]{color_map.get(level, Fore.WHITE)} {message}{Style.RESET_ALL}"
    if data:
        log_message += f"\n{json.dumps(data, indent=2, ensure_ascii=False)}"
    print(log_message)

def load_tokens_from_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        logger(f"Error: File not found {filename}", 'error')
        return []

def load_proxies_from_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        logger(f"Error: File not found {filename}", 'error')
        return []

def get_next_proxy(proxies, current_index):
    if not proxies:
        return None, 0
    proxy_url = proxies[current_index]
    next_index = (current_index + 1) % len(proxies)
    if 'http' not in proxy_url:
        proxy_url = f'http://{proxy_url}'
    return proxy_url, next_index
