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
        log_message += f"\n{json.dumps(data, indent=2, ensure_ascii=False)}"
    print(log_message)


def load_private_keys(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger(f"Error: file dompet '{filename}' tidak ditemukan.", 'error')
        return []
    except json.JSONDecodeError:
        logger(f"Error: gagal menguraikan file dompet '{filename}'. Pastikan format JSON valid.", 'error')
        return []


def load_proxies_from_file(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip()]
        if not proxies:
            logger(f"Peringatan: file proxy '{filename}' kosong.", 'info')
        else:
            logger(f"Jumlah proxy yang dimuat dari {filename}: {len(proxies)}", 'info')
        return proxies
    except FileNotFoundError:
        logger(f"Peringatan: file proxy '{filename}' tidak ditemukan. Menjalankan tanpa proxy.", 'info')
        return []


def save_tokens_to_file(tokens, path):
    try:
        if not tokens:
            return
        with open(path, 'a', encoding='utf-8') as f:
            for token in tokens:
                f.write(token + '\n')
        logger(f"Berhasil menyimpan {len(tokens)} token ke {path}", 'success')
    except IOError as e:
        logger(f'Error saat menyimpan token: {e}', 'error')


def save_wallets_to_file(wallets, path):
    """
    Menyimpan daftar wallet (array of {address, privateKey}) ke walletX.json.
    Akan menimpa file lama (menyimpan hanya wallet yang berhasil).
    """
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(wallets, f, indent=2)
        logger(f"Berhasil menyimpan {len(wallets)} wallet berhasil ke {path}", 'success')
    except IOError as e:
        logger(f'Error saat menyimpan wallet ke {path}: {e}', 'error')


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
        raise Exception('Tidak menerima nonce dari endpoint sign-in.')
    return result


async def generate_signature(wallet):
    # Tetap gunakan None untuk proxy pada step ini sesuai implementasi awal
    data = await send_sign_in_request(wallet.address, None)
    now_utc = datetime.now(timezone.utc)
    issued_at = now_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    siwe_message = SiweMessage(
        domain="fishingfrenzy.co",
        address=wallet.address,
        statement="Dengan menandatangani, Anda membuktikan bahwa Anda memiliki wallet ini dan login. Ini tidak memicu transaksi atau biaya.",
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
        raise Exception('Autentikasi gagal, tidak menerima token.')
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
        raise Exception('Login gagal, tidak menerima access token.')
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
    logger("Berhasil menerapkan kode referral.", 'success')
    return response.json()


def generate_wallets():
    """
    Menghasilkan wallet baru dan mengembalikan tuple (code_reff, wallet_data)
    Tidak langsung menyimpan walletX.json — hanya mengembalikan data untuk diproses.
    """
    wallet_data = []
    try:
        code_reff = input(Fore.YELLOW + "Masukkan kode referral Anda: " + Style.RESET_ALL)
        if not code_reff:
            logger("Kode referral tidak boleh kosong.", "error")
            return None, []
        number_wallet_str = input(Fore.YELLOW + 'Masukkan jumlah wallet referral yang ingin digenerate: ' + Style.RESET_ALL)
        number_wallet = int(number_wallet_str)
        if number_wallet <= 0:
            logger("Jumlah harus lebih besar dari 0.", 'error')
            return None, []
    except ValueError:
        logger("Masukkan angka yang valid.", 'error')
        return None, []
    logger(f"Menyiapkan pembuatan {number_wallet} wallet...", 'info')
    for _ in range(number_wallet):
        account = Account.create()
        wallet_data.append({
            'address': account.address,
            'privateKey': account.key.hex()
        })
    logger(f"Pembuatan wallet selesai, {number_wallet} wallet telah dibuat (belum disimpan ke file).", 'success')
    return code_reff, wallet_data


async def worker(wallet, proxy, code_reff, semaphore):
    """
    Memproses satu wallet: autentikasi -> login -> verifikasi referral.
    Mengembalikan tuple (wallet, access_token) jika sukses, atau (wallet, None) jika gagal.
    """
    async with semaphore:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger(f"Memulai proses wallet {wallet['address']} (percobaan {attempt + 1}/{max_retries})", 'info')

                logger("Langkah 1/3: Mengautentikasi wallet...", 'info')
                privy_token = await authenticate(wallet['privateKey'], proxy)
                logger("Autentikasi berhasil.", 'success')

                logger("Langkah 2/3: Melakukan login game...", 'info')
                access_token = await login(privy_token, proxy)
                logger("Login berhasil.", 'success')

                logger("Langkah 3/3: Menerapkan kode referral...", 'info')
                await verify_reff(access_token, code_reff, proxy)

                logger(f"Wallet {wallet['address']} berhasil diproses.", 'success')
                # Kembalikan wallet dan token yang berhasil
                return wallet, access_token
            except Exception as e:
                logger(f"Error saat memproses wallet {wallet['address']} (percobaan {attempt + 1}/{max_retries}): {e}", 'error')
                if attempt < max_retries - 1:
                    logger("Akan mencoba lagi setelah 5 detik...", 'info')
                    await asyncio.sleep(5)
                else:
                    logger(f"Wallet {wallet['address']} gagal setelah {max_retries} percobaan.", 'error')
        # Gagal setelah retries
        return wallet, None


async def process_wallets(code_reff, wallets):
    """
    Memproses daftar wallet yang diberikan.
    Hanya wallet yang berhasil (menghasilkan access_token) akan disimpan ke walletX.json.
    Token yang berhasil disimpan ke tokens.txt.
    """
    if not wallets:
        logger("Tidak ada wallet untuk diproses (daftar kosong).", 'error')
        return

    proxies = load_proxies_from_file('proxies.txt')

    # Pilihan penggunaan proxy: jika tidak ada proxy, otomatis jalankan tanpa proxy.
    use_proxy = False
    if proxies:
        while True:
            choice = input(Fore.YELLOW + "Apakah ingin menggunakan proxy dari proxies.txt? [y/n]: " + Style.RESET_ALL).strip().lower()
            if choice in ('y', 'n'):
                use_proxy = (choice == 'y')
                break
            else:
                logger("Masukkan 'y' (ya) atau 'n' (tidak).", 'error')
        logger(f"Menjalankan dengan proxy: {use_proxy}", 'info')
    else:
        logger("Tidak ada proxy; menjalankan tanpa proxy.", 'info')
        use_proxy = False

    proxy_index = 0
    tasks = []
    concurrency_limit = 10
    semaphore = asyncio.Semaphore(concurrency_limit)

    # Proses semua wallet sekaligus (dengan concurrency limit)
    for wallet in wallets:
        if use_proxy:
            proxy, proxy_index = get_next_proxy(proxies, proxy_index)
        else:
            proxy = None
        tasks.append(asyncio.create_task(worker(wallet, proxy, code_reff, semaphore)))

    results = await asyncio.gather(*tasks)

    # Kumpulkan wallet yang sukses dan tokennya
    successful_wallets = []
    successful_tokens = []
    failed_count = 0
    for wallet, token in results:
        if token:
            successful_wallets.append(wallet)
            successful_tokens.append(token)
        else:
            failed_count += 1

    # Simpan token yang berhasil
    if successful_tokens:
        save_tokens_to_file(successful_tokens, 'tokens.txt')

    # Simpan ONLY wallet yang berhasil ke walletX.json (timpa file lama)
    if successful_wallets:
        save_wallets_to_file(successful_wallets, 'walletX.json')
    else:
        # Jika tidak ada yang sukses, hapus file walletX.json (opsional) atau beri peringatan.
        logger("Tidak ada wallet yang berhasil — file walletX.json tidak akan diperbarui.", 'warn')

    logger(f"Proses selesai: {len(successful_wallets)} sukses, {failed_count} gagal.", 'info')


if __name__ == '__main__':
    code_reff, wallets = generate_wallets()
    if code_reff and wallets:
        asyncio.run(process_wallets(code_reff, wallets))
