import json
import time
import uuid
import asyncio
from datetime import datetime, timezone
from eth_account import Account
from eth_account.messages import encode_defunct
from siwe import SiweMessage
import requests
from colorama import init, Fore, Style
from collections.abc import MutableMapping

init(autoreset=True)


def logger(message, level='info', data=None):
    color_map = {
        'info': Fore.CYAN,
        'debug': Fore.WHITE,
        'error': Fore.RED,
        'success': Fore.GREEN
    }
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"{Style.BRIGHT}[{timestamp}]{color_map.get(level, Fore.WHITE)} {message}{Style.RESET_ALL}"
    if data:
        log_message += f"\n{json.dumps(data, indent=2, ensure_ascii=False)}"
    print(log_message)


def load_private_keys(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger(f"错误：找不到钱包文件 {filename}。", 'error')
        return []
    except json.JSONDecodeError:
        logger(f"错误：无法解析钱包文件 {filename}。", 'error')
        return []


def load_proxies_from_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip()]
        if not proxies:
            logger(f"警告：代理文件 {filename} 为空。", 'error')
        return proxies
    except FileNotFoundError:
        logger(f"错误：找不到代理文件 {filename}。", 'error')
        return []


def save_tokens_to_file(tokens, path):
    try:
        with open(path, 'a', encoding='utf-8') as f:
            for token in tokens:
                f.write(token + '\n')
        logger(f"成功将 {len(tokens)} 个 Token 保存到 {path}", 'success')
    except IOError as e:
        logger(f'保存 Token 时出错: {e}', 'error')


def get_next_proxy(proxies, current_index):
    if not proxies:
        return None, 0
    proxy = proxies[current_index]
    next_index = (current_index + 1) % len(proxies)
    if 'http' not in proxy:
        proxy = f'http://{proxy}'
    return {'http': proxy, 'https': proxy}, next_index


async def send_sign_in_request(wallet_address, proxy):
    url = 'https://auth.privy.io/api/v1/siwe/init'
    body = {'address': wallet_address}
    headers = {
        'Content-Type': 'application/json',
        'origin': 'https://fishingfrenzy.co',
        'privy-app-id': "cm06k1f5p00obmoff19qdgri4",
        'privy-ca-id': 'a9f18efd-a143-4f50-9f96-cf2500a6cf91',
        'privy-client': 'react-auth:2.17.3'
    }
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, lambda: requests.post(url, headers=headers, json=body, proxies=proxy,
                                                                      timeout=10))
    response.raise_for_status()
    result = response.json()
    if not result.get('nonce'):
        raise Exception('未收到 nonce')
    return result


async def generate_signature(wallet):
    data = await send_sign_in_request(wallet.address, None)
    now_utc = datetime.now(timezone.utc)
    issued_at = now_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    siwe_message = SiweMessage(
        domain="fishingfrenzy.co",
        address=wallet.address,
        statement="By signing, you are proving you own this wallet and logging in. This does not initiate a transaction or cost any fees.",
        uri="https://fishingfrenzy.co",
        version="1",
        chain_id=2020,
        nonce=data['nonce'],
        issued_at=issued_at,
        resources=["https://privy.io"]
    )
    message_to_sign = siwe_message.prepare_message()
    signed_message = Account.sign_message(encode_defunct(text=message_to_sign), wallet.key)
    signature = signed_message.signature.hex()
    return message_to_sign, "0x" + signature


async def authenticate(private_key, proxy):
    account = Account.from_key(private_key)
    wallet = account
    message, signature = await generate_signature(wallet)
    url = 'https://auth.privy.io/api/v1/siwe/authenticate'
    body = {
        'message': message,
        'signature': signature,
        'chainId': "eip155:2020",
        'walletClientType': "metamask",
        'connectorType': "injected",
        'mode': "login-or-sign-up"
    }
    headers = {
        'Content-Type': 'application/json',
        'origin': 'https://fishingfrenzy.co',
        'privy-app-id': "cm06k1f5p00obmoff19qdgri4",
        'privy-ca-id': 'a9f18efd-a143-4f50-9f96-cf2500a6cf91',
        'privy-client': 'react-auth:2.17.3'
    }
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, lambda: requests.post(url, headers=headers, json=body, proxies=proxy,
                                                                      timeout=10))
    response.raise_for_status()
    result = response.json()
    if not result.get('token'):
        raise Exception('认证失败，未收到 token')
    return result['token']


async def login(privy_token, proxy):
    url = 'https://api.fishingfrenzy.co/v1/auth/login'
    body = {
        'deviceId': str(uuid.uuid4()),
        'teleUserId': None,
        'teleName': None
    }
    headers = {
        'Content-Type': 'application/json',
        'origin': 'https://fishingfrenzy.co',
        'x-privy-token': privy_token
    }
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, lambda: requests.post(url, headers=headers, json=body, proxies=proxy,
                                                                      timeout=10))
    response.raise_for_status()
    result = response.json()
    if not result.get('tokens', {}).get('access', {}).get('token'):
        raise Exception('登录失败，未收到 access token')
    return result['tokens']['access']['token']


async def verify_reff(access_token, code_reff, proxy):
    url = f'https://api.fishingfrenzy.co/v1/reference-code/verify?code={code_reff}'
    headers = {
        'Content-Type': 'application/json',
        'origin': 'https://fishingfrenzy.co',
        'authorization': f'Bearer {access_token}'
    }
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, lambda: requests.post(url, headers=headers, json={}, proxies=proxy,
                                                                      timeout=10))
    response.raise_for_status()
    logger("推荐码应用成功。", 'success')
    return response.json()


def generate_wallets():
    wallet_data = []
    try:
        code_reff = input(Fore.YELLOW + "请输入您的推荐码: " + Style.RESET_ALL)
        if not code_reff:
            logger("推荐码不能为空。", "error")
            return None
        number_wallet_str = input(Fore.YELLOW + '请输入要生成的推荐钱包数量: ' + Style.RESET_ALL)
        number_wallet = int(number_wallet_str)
        if number_wallet <= 0:
            logger("生成数量必须大于0。", "error")
            return None
    except ValueError:
        logger("请输入有效的数字。", "error")
        return None
    logger(f"准备生成 {number_wallet} 个钱包...", 'info')
    for _ in range(number_wallet):
        account = Account.create()
        wallet_data.append({
            'address': account.address,
            'privateKey': account.key.hex()
        })
    try:
        with open('walletX.json', 'w', encoding='utf-8') as f:
            json.dump(wallet_data, f, indent=2)
        logger(f"钱包生成完成，{number_wallet} 个钱包数据已保存到 walletX.json", 'success')
        return code_reff
    except IOError as e:
        logger(f"保存钱包文件时出错: {e}", 'error')
        return None


async def worker(wallet, proxy, code_reff, semaphore):
    async with semaphore:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger(f"开始处理钱包 {wallet['address']} (尝试 {attempt + 1}/{max_retries})", 'info')

                logger(f"步骤 1/3: 正在认证钱包...", 'info')
                privy_token = await authenticate(wallet['privateKey'], proxy)
                logger(f"认证成功。", 'success')

                logger(f"步骤 2/3: 正在登录游戏...", 'info')
                access_token = await login(privy_token, proxy)
                logger(f"登录成功。", 'success')

                logger(f"步骤 3/3: 正在应用推荐码...", 'info')
                await verify_reff(access_token, code_reff, proxy)

                logger(f"钱包 {wallet['address']} 所有步骤处理成功。", 'success')
                return access_token
            except Exception as e:
                logger(f"处理钱包 {wallet['address']} 时出错 (尝试 {attempt + 1}/{max_retries}): {e}", 'error')
                if attempt < max_retries - 1:
                    logger(f"将在5秒后重试...", 'info')
                    await asyncio.sleep(5)
                else:
                    logger(f"钱包 {wallet['address']} 在 {max_retries} 次尝试后最终失败。", 'error')
        return None


async def process_wallets(code_reff):
    wallets = load_private_keys('walletX.json')
    proxies = load_proxies_from_file('proxies.txt')
    if not wallets:
        return
    if not proxies:
        logger("没有可用的代理，程序无法继续。", "error")
        return
    proxy_index = 0
    tasks = []
    concurrency_limit = 10
    semaphore = asyncio.Semaphore(concurrency_limit)
    for wallet in wallets:
        proxy, proxy_index = get_next_proxy(proxies, proxy_index)
        tasks.append(worker(wallet, proxy, code_reff, semaphore))
    results = await asyncio.gather(*tasks)
    successful_tokens = [token for token in results if token]
    if successful_tokens:
        save_tokens_to_file(successful_tokens, 'tokens.txt')
    else:
        logger('本次运行未生成任何有效的 access token。', 'error')


if __name__ == '__main__':
    referral_code = generate_wallets()
    if referral_code:
        asyncio.run(process_wallets(referral_code))

