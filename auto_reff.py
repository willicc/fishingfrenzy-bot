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
        'success': Fore.GREEN,
        'warn': Fore.YELLOW
    }
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"{Style.BRIGHT}[{timestamp}]{color_map.get(level, Fore.WHITE)} {message}{Style.RESET_ALL}"
    if data:
        try:
            log_message += f"\n{json.dumps(data, indent=2, ensure_ascii=False)}"
        except Exception:
            log_message += f"\n{data}"
    print(log_message)


def load_private_keys(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger(f"Error: wallet file '{filename}' not found.", 'error')
        return []
    except json.JSONDecodeError:
        logger(f"Error: failed to parse wallet file '{filename}'. Ensure valid JSON format.", 'error')
        return []


def load_proxies_from_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip()]
        if not proxies:
            logger(f"Warning: proxy file '{filename}' is empty.", 'info')
        else:
            logger(f"Loaded {len(proxies)} proxies from {filename}", 'info')
        return proxies
    except FileNotFoundError:
        logger(f"Warning: proxy file '{filename}' not found. Running without proxy.", 'info')
        return []


def save_tokens_to_file(tokens, path):
    try:
        if not tokens:
            return
        with open(path, 'a', encoding='utf-8') as f:
            for token in tokens:
                f.write(token + '\n')
        logger(f"Saved {len(tokens)} tokens to {path}", 'success')
    except IOError as e:
        logger(f'Error saving tokens: {e}', 'error')


def save_wallets_to_file(wallets, path):
    """
    Save wallets to walletX.json using the order: address, privateKey, reff.
    Overwrites the file with only the successfully processed wallets.
    """
    try:
        # Build ordered list to ensure field order in JSON
        formatted_wallets = []
        for w in wallets:
            formatted_wallets.append({
                'address': w.get('address'),
                'privateKey': w.get('privateKey'),
                'reff': w.get('reff')  # may be None
            })
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(formatted_wallets, f, indent=2)
        logger(f"Saved {len(formatted_wallets)} successful wallets to {path}", 'success')
    except IOError as e:
        logger(f'Error saving wallets to {path}: {e}', 'error')


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
        raise Exception('Did not receive nonce from sign-in endpoint.')
    return result


async def generate_signature(wallet):
    # Keep proxy None here to match earlier approach (signing does not require proxy)
    data = await send_sign_in_request(wallet.address, None)
    now_utc = datetime.now(timezone.utc)
    issued_at = now_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    siwe_message = SiweMessage(
        domain="fishingfrenzy.co",
        address=wallet.address,
        statement="By signing you prove you own this wallet and login. This does not trigger any transaction or fee.",
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
        raise Exception('Authentication failed, did not receive token.')
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
        raise Exception('Login failed, did not receive access token.')
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
    logger("Referral code applied successfully.", 'success')
    return response.json()


async def get_account_info(access_token, proxy):
    """
    GET /v1/users/me to retrieve user's info, including referenceCode.
    """
    url = 'https://api.fishingfrenzy.co/v1/users/me'
    headers = {
        'Content-Type': 'application/json',
        'origin': 'https://fishingfrenzy.co',
        'authorization': f'Bearer {access_token}'
    }
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, lambda: requests.get(url, headers=headers, proxies=proxy, timeout=10))
    response.raise_for_status()
    return response.json()


def generate_wallets():
    """
    Generate new wallets and return (code_reff, wallet_data).
    Wallets are returned as list of dicts {address, privateKey}.
    """
    wallet_data = []
    try:
        code_reff = input(Fore.YELLOW + "Enter your referral code: " + Style.RESET_ALL)
        if not code_reff:
            logger("Referral code cannot be empty.", "error")
            return None, []
        number_wallet_str = input(Fore.YELLOW + 'Enter number of referral wallets to generate: ' + Style.RESET_ALL)
        number_wallet = int(number_wallet_str)
        if number_wallet <= 0:
            logger("Number must be greater than 0.", 'error')
            return None, []
    except ValueError:
        logger("Enter a valid number.", 'error')
        return None, []
    logger(f"Preparing to create {number_wallet} wallets...", 'info')
    for _ in range(number_wallet):
        account = Account.create()
        wallet_data.append({
            'address': account.address,
            'privateKey': account.key.hex()
        })
    logger(f"Wallet creation complete: {number_wallet} wallets created (not yet saved).", 'success')
    return code_reff, wallet_data


async def worker(wallet, proxy, code_reff):
    """
    Process a single wallet: authenticate -> login -> apply referral -> retrieve own referral code.
    Returns (wallet_with_reff, access_token) on success or (wallet, None) on failure.
    Note: semaphore and delay between actions have been removed as requested.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger(f"Processing wallet {wallet['address']} (attempt {attempt + 1}/{max_retries})", 'info')

            logger("Step 1/3: Authenticating wallet...", 'info')
            privy_token = await authenticate(wallet['privateKey'], proxy)
            logger("Authentication successful.", 'success')

            logger("Step 2/3: Logging into game...", 'info')
            access_token = await login(privy_token, proxy)
            logger("Login successful.", 'success')

            logger("Step 3/3: Applying referral code...", 'info')
            await verify_reff(access_token, code_reff, proxy)

            logger("Retrieving account info to get referral code...", 'info')
            account_info = await get_account_info(access_token, proxy)

            # Try multiple possible keys where reference code might be stored
            reference_code = None
            if isinstance(account_info, dict):
                # direct keys
                for key in ('referenceCode', 'reference', 'ref', 'refCode', 'ref_code'):
                    val = account_info.get(key)
                    if val:
                        if isinstance(val, dict):
                            reference_code = val.get('code') or val.get('referenceCode') or val.get('reference') or None
                        elif isinstance(val, str):
                            reference_code = val
                        if reference_code:
                            break
                # deeper fallback
                if not reference_code:
                    ref_obj = account_info.get('refCode') or account_info.get('ref', {})
                    if isinstance(ref_obj, dict):
                        reference_code = ref_obj.get('code') or ref_obj.get('referenceCode') or None

            wallet['reff'] = reference_code or None
            logger(f"Wallet {wallet['address']} processed successfully. Own referral: {wallet.get('reff')}", 'success')

            return wallet, access_token

        except Exception as e:
            logger(f"Error processing wallet {wallet['address']} (attempt {attempt + 1}/{max_retries}): {e}", 'error')
            if attempt < max_retries - 1:
                wait_time = 5
                logger(f"Retrying after {wait_time} seconds...", 'info')
                await asyncio.sleep(wait_time)
            else:
                logger(f"Wallet {wallet['address']} failed after {max_retries} attempts.", 'error')
    return wallet, None


async def process_wallets(code_reff, wallets):
    """
    Process provided wallet list.
    Only wallets that succeed (produce access_token and have been processed) will be saved to walletX.json.
    Successful tokens will be appended to tokens.txt.
    """
    if not wallets:
        logger("No wallets to process (empty list).", 'error')
        return

    proxies = load_proxies_from_file('proxies.txt')

    # Ask user whether to use proxies if any are loaded
    use_proxy = False
    if proxies:
        while True:
            choice = input(Fore.YELLOW + "Use proxies from proxies.txt? [y/n]: " + Style.RESET_ALL).strip().lower()
            if choice in ('y', 'n'):
                use_proxy = (choice == 'y')
                break
            else:
                logger("Enter 'y' or 'n'.", 'error')
        logger(f"Running with proxies: {use_proxy}", 'info')
    else:
        logger("No proxies found; running without proxy.", 'info')
        use_proxy = False

    # Ask for delay between wallets (kept as requested)
    try:
        delay_between_wallets = int(input(Fore.YELLOW + "Enter delay between wallets (seconds): " + Style.RESET_ALL))
        if delay_between_wallets < 0:
            delay_between_wallets = 0
            logger("Delay cannot be negative. Setting to 0.", 'warn')
    except ValueError:
        delay_between_wallets = 0
        logger("Invalid input. Setting delay to 0.", 'warn')

    proxy_index = 0
    tasks = []

    for index, wallet in enumerate(wallets):
        if use_proxy:
            proxy, proxy_index = get_next_proxy(proxies, proxy_index)
        else:
            proxy = None

        # create task for each wallet (no semaphore/concurrency limit)
        tasks.append(asyncio.create_task(worker(wallet, proxy, code_reff)))

        # Add delay between wallet creation if not the last wallet
        if index < len(wallets) - 1 and delay_between_wallets > 0:
            logger(f"Waiting {delay_between_wallets} seconds before next wallet...", 'info')
            for i in range(delay_between_wallets, 0, -1):
                logger(f"Next wallet in {i} seconds...", 'info')
                await asyncio.sleep(1)

    # Wait for all tasks to complete
    results = await asyncio.gather(*tasks)

    successful_wallets = []
    successful_tokens = []
    failed_count = 0
    for wallet, token in results:
        if token:
            # ensure wallet has reff (may be None if retrieval failed)
            successful_wallets.append(wallet)
            successful_tokens.append(token)
        else:
            failed_count += 1

    if successful_tokens:
        save_tokens_to_file(successful_tokens, 'tokens.txt')

    if successful_wallets:
        # Save only successful wallets, ensuring field order address, privateKey, reff
        save_wallets_to_file(successful_wallets, 'walletX.json')
    else:
        logger("No wallets succeeded — walletX.json will not be updated.", 'warn')

    logger(f"Process complete: {len(successful_wallets)} succeeded, {failed_count} failed.", 'info')


if __name__ == '__main__':
    code_reff, wallets = generate_wallets()
    if code_reff and wallets:
        asyncio.run(process_wallets(code_reff, wallets))
