import json
import time
import random
import asyncio
import string
import aiohttp
from aiohttp_proxy import ProxyConnector
from utils import logger


def generate_fingerprint(length=64):
    return ''.join(random.choices(string.hexdigits.lower(), k=length))


async def run_game_simulation(ws, game_state):
    await game_state['start_signal'].wait()

    fishY, netY = 450, 450
    amountEnergy = 0
    netHeight = game_state['fishSim']['ns']
    game_duration = 4000 + random.uniform(0, 1000)
    start_time = time.time() * 1000

    while not ws.closed:
        fishY += (random.random() - 0.5) * game_state['fishSim']['difficultyRate']
        fishY = max(200, min(700, fishY))
        netY += (fishY - netY) * 0.3

        if abs(netY - fishY) < netHeight / 2:
            amountEnergy += game_state['fishSim']['fillRate'] * 0.05
        else:
            amountEnergy -= game_state['fishSim']['drainRate'] * 0.05
        amountEnergy = max(0, min(1, amountEnergy))

        frameData = [round(netY), round(fishY)]
        game_state['frames'].extend([frameData] * 4)

        elapsedTime = (time.time() * 1000) - start_time
        if amountEnergy >= 1 or elapsedTime >= game_duration:
            if amountEnergy < 1:
                logger("Fishing successful, sending end payload.", 'info')

            endPayload = {
                "cmd": "end", "transactionId": game_state['transactionId'],
                "rep": {"fs": game_state['fishSim']['fs'], "ns": game_state['fishSim']['ns'], "fps": 20,
                        "frs": game_state['frames']},
                "en": 1
            }
            await ws.send_str(json.dumps(endPayload))
            # logger("Sent end payload.", 'info')
            break
        await asyncio.sleep(0.05)


async def receive_messages(ws, game_state):
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                message = json.loads(msg.data)

                if message.get('type') == 'initGame':
                    game_state['transactionId'] = message.get('data', {}).get('transactionId')
                    fish_data = message.get('data', {}).get('randomFish', {})
                    game_state['fishSim'] = {
                        'name': fish_data.get('fishName'), 'fillRate': fish_data.get('fillRate', 0.2),
                        'drainRate': fish_data.get('drainRate', 0.05),
                        'difficultyRate': fish_data.get('difficultyRate', 11),
                        'fs': 100, 'ns': 200,
                    }
                    # logger(f"Initialization successful, target fish: {game_state['fishSim']['name']}", 'info')
                    await asyncio.sleep(0.5)
                    await ws.send_str(json.dumps({"cmd": "start"}))
                    logger("Starting fishing", 'info')
                    game_state['start_signal'].set()

                elif message.get('type') == 'gameState':
                    if message.get('dir', 0) != 0 and game_state['frames']:
                        last_frame = game_state['frames'][-1]
                        if len(last_frame) == 2:
                            last_frame.extend([message.get('frame'), message.get('dir')])

                elif message.get('type') == 'gameOver':
                    logger(f"Game over: Success: {message.get('success')}, Message: {message.get('message', 'None')}",
                           'success' if message.get('success') else 'error')
                    return

            except Exception as e:
                logger(f"Error processing message: {e}", "error")
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            break


async def fishing(token, type='1', proxy=None):
    range_map = {'1': 'short_range', '2': 'mid_range', '3': 'long_range'}
    range_type = range_map.get(type, 'short_range')
    url = f"wss://api.fishingfrenzy.co/?token={token}"

    game_state = {'frames': [], 'start_signal': asyncio.Event()}

    connector = ProxyConnector.from_url(proxy, ssl=False) if proxy else aiohttp.TCPConnector(ssl=False)

    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.ws_connect(url, timeout=30) as ws:
                fingerprint = generate_fingerprint()
                await ws.send_str(json.dumps({
                    "cmd": "prepare", "range": range_type, "themeId": "6752b7a7ef93f2489cfef709",
                    "fishingMultiplier": 1, "isMonsterFight": False, "xDeviceFingerprint": fingerprint
                }))

                receiver_task = asyncio.create_task(receive_messages(ws, game_state))
                simulator_task = asyncio.create_task(run_game_simulation(ws, game_state))

                done, pending = await asyncio.wait([receiver_task, simulator_task], return_when=asyncio.FIRST_COMPLETED)

                for task in pending:
                    task.cancel()
    except Exception as e:
        logger(f"WebSocket connection or execution failed: {e}", "error")
