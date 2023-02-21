from foxglove_websocket.types import ChannelId
from foxglove_websocket.server import FoxgloveServer, FoxgloveServerListener
from foxglove_websocket import run_cancellable
import os
from pathlib import Path
import numpy as np
import depthai as dai
import cv2
import argparse as argparse
import math
import time
import struct
import json
import base64
import asyncio


pipeline = dai.Pipeline()

camRgb = pipeline.createColorCamera()
camRgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_4_K)
camRgb.setBoardSocket(dai.CameraBoardSocket.RGB)
camRgb.setInterleaved(False)
camRgb.setIspScale(1, 1)
camRgb.setFps(30)
print("ISP Width: ", camRgb.getResolution(),
      "ISP Height: ", camRgb.getResolution())

rgbOut = pipeline.createXLinkOut()
print("XLINK fps:", rgbOut.getFpsLimit())
rgbOut.setStreamName("rgb")
videoEncoder = pipeline.create(dai.node.VideoEncoder)
videoEncoder.setDefaultProfilePreset(
    camRgb.getFps(), dai.VideoEncoderProperties.Profile.MJPEG)
camRgb.video.link(videoEncoder.input)
videoEncoder.bitstream.link(rgbOut.input)


# start server and wait for foxglove connection
async def main():
        seq = 0
        with dai.Device(pipeline) as device:
            print("Opening device")
            qRgb = device.getOutputQueue("rgb", maxSize=1, blocking=False)

            start_time = time.time_ns()
            stop_time = time.time_ns()
            n_frames = 0
            while True:
                tmpTime = time.time_ns()
                sec = math.trunc(tmpTime / 1e9)
                nsec = tmpTime - sec
                await asyncio.sleep(0.000000000001)
                if qRgb.has():
                    stop_time = time.time_ns()
                    # img = qRgb.get().getCvFrame()
                    im_buf_arr = qRgb.get().getData()
                    n_frames+=1
                    if (stop_time - start_time) / 1e9 > 1:
                        print("FPS: ", n_frames /
                              ((stop_time - start_time) / 1e9))
                        n_frames = 0
                        start_time = time.time_ns()

if __name__ == "__main__":
    run_cancellable(main())
