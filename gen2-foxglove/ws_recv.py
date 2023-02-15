#!/usr/bin/env python

import asyncio
import websockets
import time


start_time = time.time_ns()
stop_time = time.time_ns()
# fps = 0
async def echo(websocket):
    async for message in websocket:
      stop_time = time.time_ns()
      # fps += 1
      # if stop_time - start_time > 1e9:
      #   print("FPS: ", fps / ((stop_time - start_time) / 1e9))
      #   fps = 0
      #   start_time = time.time_ns()

async def main():
    async with websockets.serve(echo, "localhost", 8765, max_size=300000000):
        await asyncio.Future()  # run forever

asyncio.run(main())
