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
import flatbuffers
import foxglove_schemas_flatbuffer.CompressedImage as CompressedImage
from foxglove_schemas_flatbuffer.CompressedImage import CompressedImage as CompressedImageObj
from foxglove_schemas_flatbuffer.RawImage import RawImage as RawImageObj
import foxglove_schemas_flatbuffer.Time as Time
from foxglove_schemas_flatbuffer import get_schema
import foxglove_schemas_flatbuffer.RawImage as RawImage
import websockets
from websockets.server import serve, WebSocketServer, WebSocketServerProtocol
from struct import Struct
import socket
import zmq


HOST = "localhost"  # Standard loopback interface address (localhost)
PORT = 9998  # Port to listen on (non-privileged ports are > 1023)


# Serialized flatbuffer schema
schema_data = get_schema("RawImage")
# Serialized CompressedImage message


#!/usr/bin/env python3


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
pipeline = dai.Pipeline()

resolution = (1920, 1080)
# resolution = (700, 700)
# 4k
# resolution = (3840, 2160)
camRgb = pipeline.createColorCamera()
# camRgb.setPreviewSize(resolution)
camRgb.setBoardSocket(dai.CameraBoardSocket.RGB)
camRgb.setResolution(
    dai.ColorCameraProperties.SensorResolution.THE_1080_P)  # 490000
camRgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.RGB)
camRgb.setVideoSize(resolution)
# camRgb.setInterleaved(False)
print("Is video interleaved: ", camRgb.getInterleaved())
camRgb.setFps(30)

print("ISP Width: ", camRgb.getResolution(),
      "ISP Height: ", camRgb.getResolution())

rgbOut = pipeline.createXLinkOut()
print("XLINK fps:", rgbOut.getFpsLimit())
rgbOut.setStreamName("rgb")
# videoEncoder = pipeline.create(dai.node.VideoEncoder)
# videoEncoder.setDefaultProfilePreset(
#     camRgb.getFps(), dai.VideoEncoderProperties.Profile.MJPEG)
# camRgb.video.link(videoEncoder.input)
# videoEncoder.bitstream.link(rgbOut.input)
camRgb.video.link(rgbOut.input)
MessageDataHeader = Struct("<BIQ")


async def send_message_data(
    connection: WebSocketServerProtocol,
    timestamp: int,
    payload: bytes,
):
    try:
        header = MessageDataHeader.pack(
            1, 0, timestamp
        )
        await connection.send([header, payload])
    except Exception:
        pass


# start server and wait for foxglove connection
async def main():

    context = zmq.Context()
    pull_socket = context.socket(zmq.PULL)
    pull_socket.bind("tcp://127.0.0.1:3001")

    #  Socket to talk to server
    print("Connecting to hello world server…")
    socket = context.socket(zmq.PUSH)
    socket.connect("tcp://127.0.0.1:3000")
    colorChannel = {
        "topic": "colorImage",
        "encoding": "flatbuffer",
        "schemaName": "foxglove.RawImage",
        "id": 1,
        "schema": base64.b64encode(get_schema("RawImage")).decode("ascii")
    }

    monoChannel = {
        "topic": "monoImage",
        "encoding": "flatbuffer",
        "schemaName": "foxglove.RawImage",
        "id": 2,
        "schema": base64.b64encode(get_schema("RawImage")).decode("ascii")
    }

    advertise_channels = {
        "op": "advertise",
        "channels": [colorChannel, monoChannel], }
    message = json.dumps(advertise_channels).encode("utf-8")
    print("Sending advertise: ", len(message))
    # s.sendall(len(message).to_bytes(4, byteorder="big", signed=False))
    # s.sendall(message)
    socket.send(message)
    msg = pull_socket.recv()
    first_four = msg[:4]
    # print("N Recived: ", struct.unpack(">I", first_four)[0])
    print("Received: ", msg)
    # subId and channelid
    # print("Typeof message: ", msg[4:])
    decoded = json.loads(msg)
    subid = decoded["subscriptions"][0]["id"]
    channelid = decoded["subscriptions"][0]["channelId"]
    print(subid)
    print(channelid)

    seq = 0
    with dai.Device(pipeline) as device:
        print("Opening device")

        if not args.disable_color:
            qRgb = device.getOutputQueue("rgb", maxSize=1, blocking=False)

        limit = 100
        i = 0
        start_time = time.time_ns()
        stop_time = time.time_ns()
        n_frames = 0
        while i < limit:
            i += 1
            tmpTime = time.time_ns()
            sec = math.trunc(tmpTime / 1e9)
            nsec = tmpTime - sec

            await asyncio.sleep(0.01)

            if not args.disable_color:
                limit += 1
                if qRgb.has():
                    n_frames += 1
                    stop_time = time.time_ns()
                    # img = qRgb.get().getCvFrame()
                    im_buf_arr = qRgb.get()
                    # cv2.imwrite("test.jpg", im_buf_arr.getCvFrame())
                    im_buf_arr = im_buf_arr.getData()
                    if (stop_time - start_time) / 1e9 > 1:
                        print("FPS: ", n_frames /
                              ((stop_time - start_time) / 1e9))
                        n_frames = 0
                        start_time = time.time_ns()

                    data = im_buf_arr.tobytes()

                    builder = flatbuffers.Builder(5000)
                    # CompressedImage.StartDataVector(builder, len(data))
                    # data_vector = builder.CreateByteVector(data)
                    data_vector = builder.CreateNumpyVector(im_buf_arr)

                    # data_vector = builder.EndVector()
                    bgr = builder.CreateString("nv12")
                    frame_id = builder.CreateString("+x")

                    timestamp = Time.CreateTime(builder, sec, 1)

                    RawImage.Start(builder)
                    RawImage.AddTimestamp(builder, timestamp)
                    RawImage.AddFrameId(builder, frame_id)
                    RawImage.AddWidth(builder, resolution[0])
                    RawImage.AddHeight(builder, resolution[1])
                    RawImage.AddEncoding(builder, bgr)
                    RawImage.AddStep(builder, resolution[0] * 3)
                    RawImage.AddData(builder, data_vector)
                    img = RawImage.End(builder)
                    builder.Finish(img)
                    im = RawImageObj.GetRootAsRawImage(builder.Output(), 0)
                    msg_data = builder.Output()
                    full_message = MessageDataHeader.pack(
                        1, 0, time.time_ns()) + msg_data
                    socket.send(full_message)
                    # full_message_2 = MessageDataHeader.pack(
                    #     1, 1, time.time_ns()) + msg_data
                    # socket.send(full_message_2)
                    # Dump full message to file
                    # with open("sample_msg.bin", "wb") as f:
                    #     f.write(full_message)
                    # exit()
                    # zmq
                    # print("MSG: ", len(full_message) / 1e6)
                    # break

            if cv2.waitKey(1) == "q":
                break

if __name__ == "__main__":
    run_cancellable(main())
