import asyncio
import aiohttp
from aiohttp_proxy import ProxyConnector
from utils import logger

async def fetch_with_proxy(url, options, proxy):
    connector = ProxyConnector.from_url(proxy, ssl=False) if proxy else aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        method = options.get('method', 'GET')
        try:
            async with session.request(method, url, headers=options.get('headers'), json=options.get('json'), timeout=20) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            logger(f"Network error occurred while requesting {url.split('?')[0]}: {e}", 'error')
            return None
        except asyncio.TimeoutError:
            logger(f"Request to {url.split('?')[0]} timed out", 'error')
            return None

async def get_user_info(token, proxy):
    url = 'https://api.fishingfrenzy.co/v1/users/me'
    options = {'method': 'GET', 'headers': {'Authorization': f'Bearer {token}'}}
    return await fetch_with_proxy(url, options, proxy)

async def use_item(token, proxy, item_id, user_id):
    url = f'https://api.fishingfrenzy.co/v1/items/{item_id}/use?userId={user_id}'
    options = {'method': 'GET', 'headers': {'Authorization': f'Bearer {token}'}}
    return await fetch_with_proxy(url, options, proxy)

async def buy_fishing(token, proxy, item_id, user_id):
    url = f'https://api.fishingfrenzy.co/v1/items/{item_id}/buy?userId={user_id}&quantity=1'
    options = {'method': 'GET', 'headers': {'Authorization': f'Bearer {token}'}}
    return await fetch_with_proxy(url, options, proxy)

async def claim_daily_reward(token, proxy):
    url = 'https://api.fishingfrenzy.co/v1/daily-rewards/claim'
    options = {'method': 'GET', 'headers': {'Authorization': f'Bearer {token}'}}
    return await fetch_with_proxy(url, options, proxy)

async def complete_tutorial(token, proxy, user_id):
    url = f'https://api.fishingfrenzy.co/v1/users/{user_id}/complete-tutorial'
    options = {
        'method': 'POST',
        'headers': {'Content-Type': 'application/json', 'origin': 'https://fishingfrenzy.co', 'Authorization': f'Bearer {token}'},
        'json': {}
    }
    return await fetch_with_proxy(url, options, proxy)

async def get_social_quests(token, proxy):
    url = 'https://api.fishingfrenzy.co/v1/social-quests/'
    options = {'method': 'GET', 'headers': {'Authorization': f'Bearer {token}'}}
    return await fetch_with_proxy(url, options, proxy)

async def verify_quest(token, quest_id, proxy):
    url = f'https://api.fishingfrenzy.co/v1/social-quests/{quest_id}/verify'
    options = {
        'method': 'POST',
        'headers': {'Content-Type': 'application/json', 'origin': 'https://fishingfrenzy.co', 'Authorization': f'Bearer {token}'},
        'json': {}
    }
    return await fetch_with_proxy(url, options, proxy)

async def get_inventory(token, proxy):
    url = 'https://api.fishingfrenzy.co/v1/inventory'
    options = {'method': 'GET', 'headers': {'Authorization': f'Bearer {token}'}}
    return await fetch_with_proxy(url, options, proxy)
