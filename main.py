import asyncio
import sys
import random
from utils import logger, load_tokens_from_file, load_proxies_from_file, get_next_proxy
import api
import game

# 解决 aiodns/aiohttp 在 Windows 上的事件循环兼容性问题
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def worker(token, proxy, fishing_type, semaphore):
    """
    单个账户的工作单元，包含了完整的任务决策逻辑。
    """
    async with semaphore:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger(f"开始处理 Token: ...{token[-4:]} (尝试 {attempt + 1}/{max_retries})", 'info')

                # 1. 获取用户信息
                profile = await api.get_user_info(token, proxy)
                if not profile:
                    raise Exception("获取用户信息失败")

                user_id = profile.get('id')
                logger(
                    f"账户: {user_id[-6:]} | 等级: {profile.get('level')} | 经验值: {profile.get('exp')} | 金币: {profile.get('gold')} | 能量: {profile.get('energy')}",
                    'info')

                # 2. 决策树：按优先级执行任务
                if not profile.get('isCompleteTutorial'):
                    logger(f"账户 {user_id[-6:]} | 检测到未完成新手教程，正在自动完成...", 'info')
                    await api.complete_tutorial(token, proxy, user_id)

                elif not profile.get('isClaimedDailyReward'):
                    logger(f"账户 {user_id[-6:]} | 开始每日签到...", 'info')
                    await api.claim_daily_reward(token, proxy)
                    logger(f"账户 {user_id[-6:]} | 检查可领取的社交任务...", 'info')
                    quests = await api.get_social_quests(token, proxy)
                    if quests:
                        unclaimed_quests = [q['id'] for q in quests if q.get('status') == "UnClaimed"]
                        for quest_id in unclaimed_quests:
                            if quest_id not in ['670f3bb8193d51c460247600', '670f3c40193d51c460247623',
                                                '670f3c76193d51c46024762c']:
                                logger(f"账户 {user_id[-6:]} | 正在领取任务 ID: {quest_id}", 'info')
                                await api.verify_quest(token, quest_id, proxy)

                elif profile.get('gold', 0) > 1500:
                    item_id = '66b1f692aaa0b594511c2db2'
                    logger(f"账户 {user_id[-6:]} | 金币充足，尝试购买并使用经验卷轴...", 'info')
                    buy_result = await api.buy_fishing(token, proxy, item_id, user_id)
                    if buy_result:
                        logger(f"账户 {user_id[-6:]} | 购买成功，正在使用...", 'info')
                        await api.use_item(token, proxy, item_id, user_id)

                else:
                    energy_required = {'1': 1, '2': 2, '3': 3}
                    if profile.get('energy', 0) >= energy_required.get(fishing_type, 1):
                        logger(f"账户 {user_id[-6:]} | 能量充足，开始钓鱼...", 'info')
                        await game.fishing(token, fishing_type, proxy)
                    else:
                        logger(f"账户 {user_id[-6:]} | 能量不足，检查背包...", 'warn')
                        inventory = await api.get_inventory(token, proxy)
                        items = inventory.get('list_item_info', [])
                        if items:
                            item_to_use = items[0]
                            logger(f"账户 {user_id[-6:]} | 找到物品 '{item_to_use['name']}'，正在使用...", 'info')
                            await api.use_item(token, proxy, item_to_use['id'], user_id)
                        else:
                            logger(f"账户 {user_id[-6:]} | 背包为空，无法恢复能量。", 'warn')

                logger(f"账户 ...{token[-4:]} 处理成功。", 'success')
                return

            except Exception as e:
                logger(f"处理 Token ...{token[-4:]} 时出错: {e}", 'error')
                if attempt < max_retries - 1:
                    logger(f"将在5秒后重试...", 'info')
                    await asyncio.sleep(5)
                else:
                    logger(f"Token ...{token[-4:]} 在 {max_retries} 次尝试后最终失败。", 'error')


async def main():
    tokens = load_tokens_from_file('tokens.txt')
    proxies = load_proxies_from_file('proxies.txt')

    try:
        fishing_type = input('请选择钓鱼类型\n1. 短距离\n2. 中距离\n3. 长距离\n请输入您的选择 (1, 2, 3): ')
        if fishing_type not in ['1', '2', '3']:
            logger("无效的选择，请输入 1, 2, 或 3。", "error")
            return
    except KeyboardInterrupt:
        logger("用户中断了输入。", "info")
        return

    if not tokens:
        logger("tokens.txt 为空或不存在，程序退出。", "error")
        return
    if not proxies:
        logger("proxies.txt 为空或不存在，程序将不使用代理运行。", "warn")

    proxy_index = 0

    # 定义每个账户任务启动之间的随机延迟范围（秒）
    INTER_ACCOUNT_DELAY_MIN = 1
    INTER_ACCOUNT_DELAY_MAX = 3

    while True:
        tasks = []
        concurrency_limit = 10
        semaphore = asyncio.Semaphore(concurrency_limit)

        logger(f"开始新一轮处理，共 {len(tokens)} 个账户。", 'info')

        for token in tokens:
            proxy = None
            if proxies:
                proxy, proxy_index = get_next_proxy(proxies, proxy_index)

            # 通过 asyncio.create_task 立即调度 worker 协程
            # 这确保了任务在创建后就开始运行，而不是等待 gather
            task = asyncio.create_task(worker(token, proxy, fishing_type, semaphore))
            tasks.append(task)

            # 在启动下一个账户任务前，加入一个随机的短暂延迟
            # 这样可以错开每个任务的启动时间，避免瞬时并发过高
            delay = random.uniform(INTER_ACCOUNT_DELAY_MIN, INTER_ACCOUNT_DELAY_MAX)
            logger(f"等待 {delay:.2f} 秒后启动下一个账户任务...", 'debug')
            await asyncio.sleep(delay)

        await asyncio.gather(*tasks)

        logger(f'所有账户处理完毕，等待 15 秒后开始下一轮...', 'info')
        await asyncio.sleep(15)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger("程序被用户手动中断。", "info")

