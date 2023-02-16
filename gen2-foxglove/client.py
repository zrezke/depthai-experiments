# echo-server.py

from enum import IntEnum
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
import websockets
import socket

HOST = "localhost"  # Standard loopback interface address (localhost)
PORT = 9999  # Port to listen on (non-privileged ports are > 1023)


#!/usr/bin/env python3

# from foxglove_websocket import run_cancellable
# from foxglove_websocket.websocket import Foxglovewebsocket, FoxglovewebsocketListener
# from foxglove_websocket.types import ChannelId

# try:
#     from projector_device import PointCloudVisualizer
# except ImportError as e:
#     raise ImportError(
#         f"Error occured when importing PCL projector: {e}")

parser = argparse.ArgumentParser()
parser.add_argument('-l', '--left', default=False,
                    action="store_true", help="Enable streaming from left camera")
parser.add_argument('-r', '--right', default=False,
                    action="store_true", help="Enable streaming from right camera")
parser.add_argument('-dpcl', '--disable_pcl', default=False,
                    action="store_true", help="Disable streaming point cloud from camera")
parser.add_argument('-dc', '--disable_color', default=False,
                    action="store_true", help="Disable streaming color camera")
args = parser.parse_args()
print(args)
# Depth resolution
resolution = (4096, 2160)  # 24 FPS (without visualization)

# parameters to speed up visualization
downsample_pcl = True  # downsample the pointcloud before operating on it and visualizing

# StereoDepth config options.
# whether or not to align the depth image on host (As opposed to on device), only matters if align_depth = True
lrcheck = True  # Better handling for occlusions
extended = False  # Closer-in minimum depth, disparity range is doubled
subpixel = True  # True  # Better accuracy for longer distance, fractional disparity 32-levels

pipeline = dai.Pipeline()

camRgb = pipeline.createColorCamera()
camRgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_4_K)
camRgb.setBoardSocket(dai.CameraBoardSocket.RGB)
camRgb.setInterleaved(False)
camRgb.setIspScale(1, 1)
camRgb.setFps(30)
print("ISP Width: ", camRgb.getResolution(),
      "ISP Height: ", camRgb.getResolution())

# camRgb.isp.link(rgbOut.input)
# Create ColorCamera beforehand
# Set H265 encoding for the ColorCamera video output
videoEncoder = pipeline.create(dai.node.VideoEncoder)
videoEncoder.setDefaultProfilePreset(camRgb.getFps(), dai.VideoEncoderProperties.Profile.MJPEG)
camRgb.video.link(videoEncoder.input)

rgbOut = pipeline.createXLinkOut()
rgbOut.setStreamName("rgb")
videoEncoder.bitstream.link(rgbOut.input)
#camRgb.isp.link(rgbOut.input)

class BinaryOpcode(IntEnum):
    MESSAGE_DATA = 1

MessageDataHeader = struct.Struct("<BIQ")
async def main():

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        new_channel = {
            "topic": "colorImage",
            "encoding": "json",
            "schemaName": "ros.sensor_msgs.CompressedImage",
            "id": 1,
            "schema": json.dumps(
                        {
                            "type": "object",
                            "properties": {
                                "header": {
                                    "type": "object",
                                    "properties": {
                                        "stamp": {
                                            "type": "object",
                                            "properties": {
                                                "sec": {"type": "integer"},
                                                "nsec": {"type": "integer"},
                                            },
                                        },
                                    },
                                },
                                "format": {"type": "string"},
                                "data": {"type": "string", "contentEncoding": "base64"},
                            },
                        },
            ),
        }
        advertise_channels = {
            "op": "advertise",
            "channels": [new_channel], }
        message = json.dumps(advertise_channels).encode("utf-8")
        print("Sending advertise: ", len(message))
        s.sendall(len(message).to_bytes(4, byteorder="big", signed=False))
        s.sendall(message)
        msg = s.recv(1024)
        first_four = msg[:4]
        print("N Recived: ", struct.unpack(">I", first_four)[0])
        print("Received: ", msg)
        # subId and channelid
        print("Typeof message: ", msg[4:])
        decoded = json.loads(msg[4:])
        subid = decoded["subscriptions"][0]["id"]
        channelid = decoded["subscriptions"][0]["channelId"]
        print(subid)
        print(channelid)

        while True:
            # data = conn.recv(1024)

            # if not data:
            #     break
            with dai.Device(pipeline) as device:
                print("Opening device")
                if not args.disable_color:
                    qRgb = device.getOutputQueue(
                        "rgb", maxSize=1, blocking=False)

                limit = 100
                i = 0
                start_time = time.time_ns()
                stop_time = time.time_ns()
                n_frames = 0
                j = 0
                frames = []
                while i < limit:
                    i += 1
                    tmpTime = time.time_ns()
                    sec = math.trunc(tmpTime / 1e9)
                    nsec = tmpTime - sec

                    await asyncio.sleep(0.000000000001)

                    if not args.disable_color:
                        limit += 1
                        if qRgb.has():
                            n_frames += 1
                            stop_time = time.time_ns()
                            #img = qRgb.get().getCvFrame()
                            img = qRgb.get().getData()
                            if (stop_time - start_time) / 1e9 > 1:
                                print("FPS: ", n_frames /
                                      ((stop_time - start_time) / 1e9))
                                n_frames = 0
                                start_time = time.time_ns()

                            #is_success, im_buf_arr = cv2.imencode(".jpg", img)

                            # read from .jpeg format to buffer of bytes
                            #byte_im = im_buf_arr.tobytes()
                            byte_im = img.tobytes()

                            # data must be encoded in base64
                            data = base64.b64encode(byte_im).decode("ascii")

                            # data is sent with json (data must be in above schema order)
                            message = json.dumps(
                                {
                                    "header": {"stamp": {"sec": sec, "nsec": nsec}},
                                    "format": "jpeg",
                                    "data": data,
                                }
                            ).encode("utf-8")
                            # print("MEssage; ", message.encode("utf-8"))
                            # print("Message size: ", len(message),
                            #       " bytes, MB: ", len(message)/1e6, " MB")
                            # message = json.dumps({
                            #     "message": "LOL"
                            # })
                            s.sendall(len(message).to_bytes(
                                signed=False, byteorder="big", length=4))
                            full_message = MessageDataHeader.pack(BinaryOpcode.MESSAGE_DATA, subid, time.time_ns())
                            #print("Sending message: ", len(full_message + message))
                            s.sendall(full_message + message)

                            # print("
if __name__ == "__main__":
    # run_cancellable(main())
    asyncio.run(main())
