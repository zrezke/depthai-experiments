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
camRgb = pipeline.createColorCamera()
camRgb.setPreviewSize(resolution)
camRgb.setBoardSocket(dai.CameraBoardSocket.RGB)
camRgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
camRgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.RGB)
camRgb.setFps(60)

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
camRgb.preview.link(rgbOut.input)


# start server and wait for foxglove connection
async def main():
    class Listener(FoxgloveServerListener):
        def on_subscribe(self, server: FoxgloveServer, channel_id: ChannelId):
            print("First client subscribed to", channel_id)

        def on_unsubscribe(self, server: FoxgloveServer, channel_id: ChannelId):
            print("Last client unsubscribed from", channel_id)

    async with FoxgloveServer("0.0.0.0", 8765, "DepthAI server") as server:
        server.set_listener(Listener())

        colorChannel = await server.add_channel({
            "topic": "colorImage",
            "encoding": "flatbuffer",
            "schemaName": "foxglove.RawImage",
            "schema": base64.b64encode(get_schema("RawImage")).decode("ascii")
            }
        )

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
                        # data_vector = builder.EndVector()
                        bgr = builder.CreateString("rgb8")
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
                        # print("Sent data length: ", cim.Data(0), " Actual: ", data)
                        msg_data = builder.Output()
                        # open("test.bin", "wb").write(im.DataAsNumpy().tobytes())
                        # open("test2.bin", "wb").write(im_buf_arr.tobytes())
                        # cv2.imwrite("test.png", im_buf_arr.reshape(
                        #     resolution[1], resolution[0], 3))
                        # exit(0)
                        await server.send_message(colorChannel, time.time_ns(), msg_data)

                if cv2.waitKey(1) == "q":
                    break

if __name__ == "__main__":
    run_cancellable(main())
