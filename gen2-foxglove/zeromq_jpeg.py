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
PORT = 9999  # Port to listen on (non-privileged ports are > 1023)



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

# 4k
resolution = (1920, 1080)
camRgb = pipeline.createColorCamera()
camRgb.setPreviewSize(resolution)
camRgb.setBoardSocket(dai.CameraBoardSocket.RGB)
camRgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_4_K)
# camRgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.RGB)
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
# camRgb.preview.link(rgbOut.input)
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
        "schemaName": "foxglove.CompressedImage",
        "id": 1,
        "schema": base64.b64encode(get_schema("CompressedImage")).decode("ascii")
    }
    monoChannel = {
        "topic": "monoImage",
        "encoding": "flatbuffer",
        "schemaName": "foxglove.CompressedImage",
        "id": 2,
        "schema": base64.b64encode(get_schema("CompressedImage")).decode("ascii")
    }
    advertise_channels = {
        "op": "advertise",
        "channels": [colorChannel, monoChannel], }

    message = json.dumps(advertise_channels).encode("utf-8")
    print("Sending advertise: ", len(message))
    socket.send(message)
    msg = pull_socket.recv()
    print("Received: ", msg)
    # subId and channelid
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

            await asyncio.sleep(0.000000000001)

            if not args.disable_color:
                limit += 1
                if qRgb.has():
                    n_frames += 1
                    stop_time = time.time_ns()
                    # img = qRgb.get().getCvFrame()
                    im_buf_arr = qRgb.get().getData()
                    if (stop_time - start_time) / 1e9 > 1:
                        print("FPS: ", n_frames /
                                ((stop_time - start_time) / 1e9))
                        n_frames = 0
                        start_time = time.time_ns()

                    # data = im_buf_arr.tobytes()

                    builder = flatbuffers.Builder(5000)
                    # CompressedImage.StartDataVector(builder, len(data))
                    # data_vector = builder.CreateByteVector(data)
                    data_vector = builder.CreateNumpyVector(im_buf_arr)
                    jpeg = builder.CreateString("jpeg")
                    frame_id = builder.CreateString("+x")
                    timestamp = Time.CreateTime(builder, sec, 1)

                    CompressedImage.Start(builder)
                    CompressedImage.AddTimestamp(builder, timestamp)
                    CompressedImage.AddFrameId(builder, frame_id)
                    CompressedImage.AddData(builder, data_vector)
                    CompressedImage.AddFormat(builder, jpeg)
                    img = CompressedImage.End(builder)
                    builder.Finish(img)
                    im = CompressedImageObj.GetRootAsCompressedImage(builder.Output(), 0)
                    # print("Sent data length: ", cim.Data(0), " Actual: ", data)
                    msg_data = builder.Output()
                    # break
                    # open("test.bin", "wb").write(im.DataAsNumpy().tobytes())
                    # open("test2.bin", "wb").write(im_buf_arr.tobytes())
                    # cv2.imwrite("test.png", im_buf_arr.reshape(
                    #     resolution[1], resolution[0], 3))

                    full_message_1 = MessageDataHeader.pack(1, subid, time.time_ns()) + bytes(msg_data)
                    # #open("actual_jpg.jpg", "wb").write(bytes(msg_data))
                    # #open("im_buf_arr.jpg", "wb").write(im_buf_arr.tobytes())
                    # open("raw_actual_jpg.bin", "w").write(",".join([str(int(i)) for i in im_buf_arr.tobytes()]))
                    # #open("jpgtest.jpeg", "wb").write(im.DataAsNumpy().tobytes())
                    #break
                    socket.send(full_message_1)

                    print("MSG: ", len(full_message_1) / 1e6)

                    # print("Img size B: ", len(im_buf_arr.tobytes()))
                    # print("MSG Size B: ", len(full_message))
                    # raw_json = {
                    #     i: b for i,b in enumerate(bytes(msg_data))
                    # }
                    # open("raw_jpg.json", "w").write(json.dumps(raw_json))
                    # open("raw_jpg.bin", "w").write(",".join([str(int(i)) for i in bytes(im.DataAsNumpy().tobytes())]))
                    # open("raw_actual_jpg.bin", "w").write(",".join([str(int(i)) for i in im_buf_arr.tobytes()]))
                    # open("msg_header.bin", "w").write(",".join([str(int(i)) for i in full_message[:13]]))
                    # break

            if cv2.waitKey(1) == "q":
                break

if __name__ == "__main__":
    run_cancellable(main())
