import asyncio
import sys
import random
from utils import logger, load_tokens_from_file, load_proxies_from_file, get_next_proxy
import api
import game

# Perbaikan kompatibilitas loop event aiodns/aiohttp pada Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def worker(token, proxy, fishing_type, semaphore):
    """
    Unit kerja untuk satu akun, berisi logika keputusan dan eksekusi tugas.
    """
    async with semaphore:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger(f"Memulai proses Token: ...{token[-4:]} (percobaan {attempt + 1}/{max_retries})", 'info')

                # 1. Ambil informasi pengguna
                profile = await api.get_user_info(token, proxy)
                if not profile:
                    raise Exception("Gagal mengambil informasi pengguna")

                user_id = profile.get('id')
                logger(
                    f"Akun: {user_id[-6:]} | Level: {profile.get('level')} | Exp: {profile.get('exp')} | Koin: {profile.get('gold')} | Energi: {profile.get('energy')}",
                    'info')

                # 2. Pohon keputusan: jalankan tugas berdasarkan prioritas
                if not profile.get('isCompleteTutorial'):
                    logger(f"Akun {user_id[-6:]} | Terdeteksi belum menyelesaikan tutorial, sedang menyelesaikan otomatis...", 'info')
                    await api.complete_tutorial(token, proxy, user_id)

                elif not profile.get('isClaimedDailyReward'):
                    logger(f"Akun {user_id[-6:]} | Memulai klaim hadiah harian...", 'info')
                    await api.claim_daily_reward(token, proxy)
                    logger(f"Akun {user_id[-6:]} | Memeriksa tugas sosial yang bisa diklaim...", 'info')
                    quests = await api.get_social_quests(token, proxy)
                    if quests:
                        unclaimed_quests = [q['id'] for q in quests if q.get('status') == "UnClaimed"]
                        for quest_id in unclaimed_quests:
                            if quest_id not in ['670f3bb8193d51c460247600', '670f3c40193d51c460247623',
                                                '670f3c76193d51c46024762c']:
                                logger(f"Akun {user_id[-6:]} | Mengklaim tugas ID: {quest_id}", 'info')
                                await api.verify_quest(token, quest_id, proxy)

                elif profile.get('gold', 0) > 1500:
                    item_id = '66b1f692aaa0b594511c2db2'
                    logger(f"Akun {user_id[-6:]} | Koin mencukupi, mencoba membeli dan memakai gulungan EXP...", 'info')
                    buy_result = await api.buy_fishing(token, proxy, item_id, user_id)
                    if buy_result:
                        logger(f"Akun {user_id[-6:]} | Pembelian berhasil, sedang digunakan...", 'info')
                        await api.use_item(token, proxy, item_id, user_id)

                else:
                    energy_required = {'1': 1, '2': 2, '3': 3}
                    if profile.get('energy', 0) >= energy_required.get(fishing_type, 1):
                        logger(f"Akun {user_id[-6:]} | Energi cukup, memulai memancing...", 'info')
                        await game.fishing(token, fishing_type, proxy)
                    else:
                        logger(f"Akun {user_id[-6:]} | Energi tidak cukup, memeriksa inventaris...", 'warn')
                        inventory = await api.get_inventory(token, proxy)
                        items = inventory.get('list_item_info', [])
                        if items:
                            item_to_use = items[0]
                            logger(f"Akun {user_id[-6:]} | Ditemukan item '{item_to_use['name']}', sedang digunakan...", 'info')
                            await api.use_item(token, proxy, item_to_use['id'], user_id)
                        else:
                            logger(f"Akun {user_id[-6:]} | Inventaris kosong, tidak ada item untuk mengembalikan energi.", 'warn')

                logger(f"Akun ...{token[-4:]} berhasil diproses.", 'success')
                return

            except Exception as e:
                logger(f"Error saat memproses Token ...{token[-4:]}: {e}", 'error')
                if attempt < max_retries - 1:
                    logger("Akan mencoba ulang setelah 5 detik...", 'info')
                    await asyncio.sleep(5)
                else:
                    logger(f"Token ...{token[-4:]} gagal setelah {max_retries} percobaan.", 'error')


async def main():
    tokens = load_tokens_from_file('tokens.txt')
    proxies = load_proxies_from_file('proxies.txt')

    try:
        fishing_type = input('Pilih tipe memancing\n1. Jarak Dekat\n2. Jarak Menengah\n3. Jarak Jauh\nMasukkan pilihan Anda (1, 2, 3): ')
        if fishing_type not in ['1', '2', '3']:
            logger("Pilihan tidak valid, masukkan 1, 2, atau 3.", "error")
            return
    except KeyboardInterrupt:
        logger("Input dibatalkan oleh pengguna.", "info")
        return

    if not tokens:
        logger("tokens.txt kosong atau tidak ditemukan, program keluar.", "error")
        return
    if not proxies:
        logger("proxies.txt kosong atau tidak ditemukan, program akan berjalan tanpa proxy.", "warn")

    proxy_index = 0

    # Rentang delay acak antar akun (detik)
    INTER_ACCOUNT_DELAY_MIN = 1
    INTER_ACCOUNT_DELAY_MAX = 3

    while True:
        tasks = []
        concurrency_limit = 10
        semaphore = asyncio.Semaphore(concurrency_limit)

        logger(f"Memulai ronde baru, total {len(tokens)} akun.", 'info')

        for token in tokens:
            proxy = None
            if proxies:
                proxy, proxy_index = get_next_proxy(proxies, proxy_index)

            # Menjadwalkan worker segera agar tugas langsung berjalan
            task = asyncio.create_task(worker(token, proxy, fishing_type, semaphore))
            tasks.append(task)

            # Delay acak sebelum memulai akun berikutnya untuk meratakan beban
            delay = random.uniform(INTER_ACCOUNT_DELAY_MIN, INTER_ACCOUNT_DELAY_MAX)
            logger(f"Menunggu {delay:.2f} detik sebelum memulai tugas akun berikutnya...", 'debug')
            await asyncio.sleep(delay)

        await asyncio.gather(*tasks)

        logger('Semua akun telah diproses, menunggu 15 detik sebelum ronde berikutnya...', 'info')
        await asyncio.sleep(15)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger("Program dihentikan oleh pengguna.", "info")
