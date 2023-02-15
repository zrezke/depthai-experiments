#!/usr/bin/env python3
import websockets
import asyncio
import base64
import json
import struct
import time
import math

import argparse as argparse
import cv2
import depthai as dai
import numpy as np
from pathlib import Path
import os
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


def create_xyz(width, height, camera_matrix):
    xs = np.linspace(0, width - 1, width, dtype=np.float32)
    ys = np.linspace(0, height - 1, height, dtype=np.float32)

    # generate grid by stacking coordinates
    base_grid = np.stack(np.meshgrid(xs, ys))  # WxHx2
    points_2d = base_grid.transpose(1, 2, 0)  # 1xHxWx2

    # unpack coordinates
    u_coord: np.array = points_2d[..., 0]
    v_coord: np.array = points_2d[..., 1]

    # unpack intrinsics
    fx: np.array = camera_matrix[0, 0]
    fy: np.array = camera_matrix[1, 1]
    cx: np.array = camera_matrix[0, 2]
    cy: np.array = camera_matrix[1, 2]

    # projective
    x_coord: np.array = (u_coord - cx) / fx
    y_coord: np.array = (v_coord - cy) / fy

    xyz = np.stack([x_coord, y_coord], axis=-1)
    return np.pad(xyz, ((0, 0), (0, 0), (0, 1)), "constant", constant_values=1.0)


def getPath(resolution):
    (width, heigth) = resolution
    path = Path("models", "out")
    path.mkdir(parents=True, exist_ok=True)
    name = f"pointcloud_{width}x{heigth}"

    return_path = str(path / (name + '.blob'))
    if os.path.exists(return_path):
        return return_path


def configureDepthPostProcessing(stereoDepthNode):
    """
    In-place post-processing configuration for a stereo depth node
    The best combo of filters is application specific. Hard to say there is a one size fits all.
    They also are not free. Even though they happen on device, you pay a penalty in fps.
    """
    stereoDepthNode.setDefaultProfilePreset(
        dai.node.StereoDepth.PresetMode.HIGH_DENSITY)

    # stereoDepthNode.initialConfig.setBilateralFilterSigma(16)
    config = stereoDepthNode.initialConfig.get()
    config.postProcessing.speckleFilter.enable = True
    config.postProcessing.speckleFilter.speckleRange = 60
    config.postProcessing.temporalFilter.enable = True

    config.postProcessing.spatialFilter.holeFillingRadius = 2
    config.postProcessing.spatialFilter.numIterations = 1
    config.postProcessing.thresholdFilter.minRange = 700  # mm
    config.postProcessing.thresholdFilter.maxRange = 4000  # mm
    # config.postProcessing.decimationFilter.decimationFactor = 1
    config.censusTransform.enableMeanMode = True
    config.costMatching.linearEquationParameters.alpha = 0
    config.costMatching.linearEquationParameters.beta = 2
    stereoDepthNode.initialConfig.set(config)
    stereoDepthNode.setLeftRightCheck(lrcheck)
    stereoDepthNode.setExtendedDisparity(extended)
    stereoDepthNode.setSubpixel(subpixel)
    stereoDepthNode.setRectifyEdgeFillColor(
        0)  # Black, to better see the cutout


def get_resolution(width):
    if width == 480:
        return dai.MonoCameraProperties.SensorResolution.THE_480_P
    elif width == 720:
        return dai.MonoCameraProperties.SensorResolution.THE_720_P
    elif width == 800:
        return dai.MonoCameraProperties.SensorResolution.THE_800_P
    else:
        return dai.MonoCameraProperties.SensorResolution.THE_400_P


pipeline = dai.Pipeline()

camRgb = pipeline.createColorCamera()
camRgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_4_K)
camRgb.setBoardSocket(dai.CameraBoardSocket.RGB)
camRgb.setInterleaved(False)
camRgb.setIspScale(1, 1)
print("ISP Width: ", camRgb.getResolution(),
      "ISP Height: ", camRgb.getResolution())

rgbOut = pipeline.createXLinkOut()
print("XLINK fps:", rgbOut.getFpsLimit())
rgbOut.setStreamName("rgb")
camRgb.isp.link(rgbOut.input)


# # Configure Camera Properties
# left = pipeline.createMonoCamera()
# left.setResolution(get_resolution(resolution[1]))
# left.setBoardSocket(dai.CameraBoardSocket.LEFT)

# # left camera output
# leftOut = pipeline.createXLinkOut()
# leftOut.setStreamName("left")
# left.out.link(leftOut.input)

# right = pipeline.createMonoCamera()
# right.setResolution(get_resolution(resolution[1]))
# right.setBoardSocket(dai.CameraBoardSocket.RIGHT)

# # right camera output
# rightOut = pipeline.createXLinkOut()
# rightOut.setStreamName("right")
# right.out.link(rightOut.input)

# stereo = pipeline.createStereoDepth()
# configureDepthPostProcessing(stereo)
# left.out.link(stereo.left)
# right.out.link(stereo.right)

# Depth -> PointCloud
# nn = pipeline.createNeuralNetwork()
# nn.setBlobPath(getPath(resolution))
# stereo.depth.link(nn.inputs["depth"])

# xyz_in = pipeline.createXLinkIn()
# xyz_in.setMaxDataSize(6144000)
# xyz_in.setStreamName("xyz_in")
# xyz_in.out.link(nn.inputs["xyz"])

# # Only send xyz data once, and always reuse the message
# nn.inputs["xyz"].setReusePreviousMessage(True)

# pointsOut = pipeline.createXLinkOut()
# pointsOut.setStreamName("pcl")
# nn.out.link(pointsOut.input)

# with dai.Device(pipeline) as device:
#     qRgb = device.getOutputQueue("rgb", maxSize=1, blocking=False)
#     start_time = time.time_ns()
#     stop_time = time.time_ns()
#     n_frames = 0
#     print("USB SPEED: ", device.getUsbSpeed())
#     while True:
#             n_frames += 1
#             qRgb.get()
#             stop_time = time.time_ns()
#             if stop_time - start_time > 1e9:
#                 print("FPS: ", n_frames / ((stop_time - start_time) / 1e9))
#                 n_frames = 0
#                 start_time = time.time_ns()


# start websocket and wait for foxglove connection


async def main():
    async with websockets.connect("ws://localhost:8765", ) as websocket:
        # websocket.(True)
        # create schema for the type of message that will be sent over to foxglove
        # for more details on how the schema must look like visit:
        # http://docs.ros.org/en/noetic/api/sensor_msgs/html/index-msg.html
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
                        img = qRgb.get().getCvFrame()
                        if (stop_time - start_time) / 1e9 > 1:
                            print("FPS: ", n_frames /
                                  ((stop_time - start_time) / 1e9))
                            n_frames = 0
                            start_time = time.time_ns()

                        is_success, im_buf_arr = cv2.imencode(".jpg", img)

                        # read from .jpeg format to buffer of bytes
                        byte_im = im_buf_arr.tobytes()

                        # data must be encoded in base64
                        data = base64.b64encode(byte_im).decode("ascii")

                        # data is sent with json (data must be in above schema order)
                        message = json.dumps(
                            {
                                "header": {"stamp": {"sec": sec, "nsec": nsec}},
                                "format": "jpeg",
                                "data": data,
                            }
                        )
                        print("Message size: ", len(message),
                              " bytes, MB: ", len(message)/1e6, " MB")
                        await websocket.send(
                            message.encode("utf8")
                        )
                        frames = []

                if cv2.waitKey(1) == "q":
                    break

if __name__ == "__main__":
    # run_cancellable(main())
    asyncio.run(main())
