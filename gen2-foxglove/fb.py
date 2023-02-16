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
import foxglove_schemas_flatbuffer.Time as Time
from foxglove_schemas_flatbuffer import get_schema

# Serialized flatbuffer schema
schema_data = get_schema("CompressedImage")
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
    class Listener(FoxgloveServerListener):
        def on_subscribe(self, server: FoxgloveServer, channel_id: ChannelId):
            print("First client subscribed to", channel_id)

        def on_unsubscribe(self, server: FoxgloveServer, channel_id: ChannelId):
            print("Last client unsubscribed from", channel_id)

    async with FoxgloveServer("0.0.0.0", 8765, "DepthAI server") as server:
        server.set_listener(Listener())

        # colorChannel = await server.add_channel(
        #     {
        #         "topic": "colorImage",
        #         "encoding": "json",
        #         "schemaName": "ros.sensor_msgs.CompressedImage",
        #         "schema": json.dumps(
        #             {
        #                 "type": "object",
        #                 "properties": {
        #                     "header": {
        #                         "type": "object",
        #                         "properties": {
        #                             "stamp": {
        #                                 "type": "object",
        #                                 "properties": {
        #                                     "sec": {"type": "integer"},
        #                                     "nsec": {"type": "integer"},
        #                                 },
        #                             },
        #                         },
        #                     },
        #                     "format": {"type": "string"},
        #                     "data": {"type": "string", "contentEncoding": "base64"},
        #                 },
        #             },
        #         ),
        #     }
        # )

        colorChannel = await server.add_channel({
            "topic": "colorImage",
            "encoding": "flatbuffer",
            "schemaName": "foxglove.CompressedImage",
            "schema": base64.b64encode(get_schema("CompressedImage")).decode("ascii")
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

                        # is_success, im_buf_arr = cv2.imencode(".jpg", img)

                        # read from .jpeg format to buffer of bytes
                        byte_im = im_buf_arr.tobytes()

                        # data must be encoded in base64
                        # data = base64.b64encode(byte_im)
                        data = byte_im

                        # # data is sent with json (data must be in above schema order)
                        # message = json.dumps(
                        #     {
                        #         "header": {"stamp": {"sec": sec, "nsec": nsec}},
                        #         "format": "jpeg",
                        #         "data": data,
                        #     }
                        # ).encode("utf8")
                        # print("Message size: ", len(message),
                        #       " bytes, MB: ", len(message)/1e6, " MB")
                        # await server.send_message(
                        #     colorChannel,
                        #     time.time_ns(),
                        #     json.dumps(
                        #         {
                        #             "header": {"stamp": {"sec": sec, "nsec": nsec}},
                        #             "format": "jpeg",
                        #             "data": data,
                        #         }
                        #     ).encode("utf8"),
                        # )
                        builder = flatbuffers.Builder(5000)
                        # CompressedImage.StartDataVector(builder, len(data))
                        data_vector = builder.CreateByteVector(data)
                        # data_vector = builder.EndVector()
                        jpeg = builder.CreateString("jpeg")
                        frame_id = builder.CreateString("+x")


                        CompressedImage.Start(builder)
                        timestamp = Time.CreateTime(builder, sec, 1)
                        CompressedImage.AddTimestamp(builder, timestamp)
                        CompressedImage.AddFrameId(builder, frame_id)
                        CompressedImage.AddData(builder, data_vector)
                        CompressedImage.AddFormat(builder, jpeg)
                        img = CompressedImage.End(builder)
                        builder.Finish(img)
                        cim = CompressedImageObj.GetRootAs(builder.Output())
                        # print("Sent data length: ", cim.Data(0), " Actual: ", data)
                        msg_data = builder.Output()
                        await server.send_message(colorChannel, time.time_ns(), msg_data)

                if cv2.waitKey(1) == "q":
                    break

if __name__ == "__main__":
    run_cancellable(main())
