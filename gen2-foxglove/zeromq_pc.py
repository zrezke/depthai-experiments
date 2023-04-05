from projector_3d import PointCloudVisualizer
import struct
from foxglove_websocket import run_cancellable
import numpy as np
import depthai as dai
import cv2
import argparse as argparse
import math
import time
import json
import base64
import asyncio
import flatbuffers
from foxglove_schemas_flatbuffer.RawImage import RawImage as ClsRawImage
from foxglove_schemas_flatbuffer.PointCloud import PointCloud as ClsPointCloud
import foxglove_schemas_flatbuffer.Time as Time
from foxglove_schemas_flatbuffer import get_schema
import foxglove_schemas_flatbuffer.RawImage as RawImage
import foxglove_schemas_flatbuffer.PointCloud as PointCloud
import foxglove_schemas_flatbuffer.Pose as Pose
from foxglove_schemas_flatbuffer import Vector3, Quaternion, PackedElementField
from struct import Struct
import zmq
import open3d as o3d
from multiprocessing import Process

# Serialized flatbuffer schema
schema_data = get_schema("PointCloud")

lrcheck = True   # Better handling for occlusions
extended = False  # Closer-in minimum depth, disparity range is doubled
subpixel = True   # Better accuracy for longer distance, fractional disparity 32-levels
# Options: MEDIAN_OFF, KERNEL_3x3, KERNEL_5x5, KERNEL_7x7
median = dai.StereoDepthProperties.MedianFilter.KERNEL_7x7
COLOR = True

print("StereoDepth config options:")
print("    Left-Right check:  ", lrcheck)
print("    Extended disparity:", extended)
print("    Subpixel:          ", subpixel)
print("    Median filtering:  ", median)



pipeline = dai.Pipeline()

monoLeft = pipeline.create(dai.node.MonoCamera)
monoLeft.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
monoLeft.setBoardSocket(dai.CameraBoardSocket.LEFT)

monoRight = pipeline.create(dai.node.MonoCamera)
monoRight.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
monoRight.setBoardSocket(dai.CameraBoardSocket.RIGHT)

stereo = pipeline.createStereoDepth()
stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
stereo.initialConfig.setMedianFilter(median)
# stereo.initialConfig.setConfidenceThreshold(255)

stereo.setLeftRightCheck(lrcheck)
stereo.setExtendedDisparity(extended)
stereo.setSubpixel(subpixel)
monoLeft.out.link(stereo.left)
monoRight.out.link(stereo.right)

config = stereo.initialConfig.get()
config.postProcessing.speckleFilter.enable = False
config.postProcessing.speckleFilter.speckleRange = 50
config.postProcessing.temporalFilter.enable = True
config.postProcessing.spatialFilter.enable = True
config.postProcessing.spatialFilter.holeFillingRadius = 2
config.postProcessing.spatialFilter.numIterations = 1
config.postProcessing.thresholdFilter.minRange = 400
config.postProcessing.thresholdFilter.maxRange = 200000
config.postProcessing.decimationFilter.decimationFactor = 1
stereo.initialConfig.set(config)

xout_depth = pipeline.createXLinkOut()
xout_depth.setStreamName("depth")
stereo.depth.link(xout_depth.input)

# xout_disparity = pipeline.createXLinkOut()
# xout_disparity.setStreamName('disparity')
# stereo.disparity.link(xout_disparity.input)

xout_colorize = pipeline.createXLinkOut()
xout_colorize.setStreamName("colorize")

if COLOR:
    camRgb = pipeline.create(dai.node.ColorCamera)
    camRgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    camRgb.setIspScale(1, 3)
    camRgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.RGB)
    camRgb.initialControl.setManualFocus(130)
    stereo.setDepthAlign(dai.CameraBoardSocket.RGB)
    camRgb.isp.link(xout_colorize.input)
else:
    stereo.rectifiedRight.link(xout_colorize.input)



class HostSync:
    def __init__(self):
        self.arrays = {}

    def add_msg(self, name, msg):
        if not name in self.arrays:
            self.arrays[name] = []
        # Add msg to array
        self.arrays[name].append({'msg': msg, 'seq': msg.getSequenceNum()})

        synced = {}
        for name, arr in self.arrays.items():
            for i, obj in enumerate(arr):
                if msg.getSequenceNum() == obj['seq']:
                    synced[name] = obj['msg']
                    break
        # If there are 3 (all) synced msgs, remove all old msgs
        # and return synced msgs
        if len(synced) == 2:  # color, depth, nn
            # Remove old msgs
            for name, arr in self.arrays.items():
                for i, obj in enumerate(arr):
                    if obj['seq'] < msg.getSequenceNum():
                        arr.remove(obj)
                    else:
                        break
            return synced
        return False


MessageDataHeader = Struct("<BIQ")

# start server and wait for foxglove connection

channel_to_subscription = {}


class ZeromqChannel:
    def __init__(self):
        self.context = zmq.Context()
        self.pull_socket = self.context.socket(zmq.PULL)
        self.pull_socket.bind("tcp://127.0.0.1:3001")

        self.push_socket = self.context.socket(zmq.PUSH)
        self.push_socket.connect("tcp://127.0.0.1:3000")

        self._poller = zmq.Poller()
        self._poller.register(self.pull_socket, zmq.POLLIN)

    def send(self, data):
        self.push_socket.send(data)

    def recv(self):
        return self.pull_socket.recv()

    def advertise(self, *channels):
        message = {
            "op": "advertise",
            "channels": channels
        }
        self.push_socket.send(json.dumps(message).encode("utf-8"))

    def poll(self, timeout, callback):
        polling_result = self._poller.poll(timeout)
        if polling_result:
            msg = self.pull_socket.recv(zmq.DONTWAIT)
            callback(msg)


def handle_studio_message(msg: bytes):
    print("Received: ", msg)
    decoded = json.loads(msg)
    subid = decoded["subscriptions"][0]["id"]
    channelid = decoded["subscriptions"][0]["channelId"]
    channel_to_subscription[channelid] = subid


def _create_xyz(device, width, height):
    calibData = device.readCalibration()
    M_right = calibData.getCameraIntrinsics(dai.CameraBoardSocket.RIGHT, dai.Size2f(width, height))
    print("M_right: ", M_right)
    camera_matrix = np.array(M_right).reshape(3, 3)

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

async def main():

    foxglove_chanel = ZeromqChannel()

    #  Socket to talk to server
    print("Connecting to hello world server…")

    colorChannel = {
        "topic": "colorImage",
        "encoding": "flatbuffer",
        "schemaName": "foxglove.RawImage",
        "id": 0,
        "schema": base64.b64encode(get_schema("RawImage")).decode("ascii")
    }

    pointcloudChannel = {
        "topic": "pointcloud",
        "encoding": "flatbuffer",
        "schemaName": "foxglove.PointCloud",
        "id": 1,
        "schema": base64.b64encode(schema_data).decode("ascii")
    }

    foxglove_chanel.advertise(colorChannel, pointcloudChannel)

    foxglove_chanel.poll(2000, handle_studio_message)

    seq = 0
    with dai.Device(pipeline) as device:
        print("Opening device")
        device.setIrLaserDotProjectorBrightness(1200)
        qs = []
        qs.append(device.getOutputQueue("depth", maxSize=1, blocking=False))
        qs.append(device.getOutputQueue("colorize", maxSize=1, blocking=False))

        try:
            from projector_3d import PointCloudVisualizer
        except ImportError as e:
            raise ImportError(
                f"\033[1;5;31mError occured when importing PCL projector: {e}. Try disabling the point cloud \033[0m "
            )

        calibData = device.readCalibration()
        if COLOR:
            w, h = camRgb.getIspSize()
            intrinsics = calibData.getCameraIntrinsics(dai.CameraBoardSocket.RGB, dai.Size2f(w, h))
        else:
            w, h = monoRight.getResolutionSize()
            intrinsics = calibData.getCameraIntrinsics(dai.CameraBoardSocket.RIGHT, dai.Size2f(w, h))
        pcl_converter = PointCloudVisualizer(intrinsics, w, h)

        serial_no = device.getMxId()
        sync = HostSync()
        depth_vis, color, rect_left, rect_right = None, None, None, None

        while True:
            foxglove_chanel.poll(1, handle_studio_message)  # 1ms timeout
            for q in qs:
                new_msg = q.tryGet()
                if new_msg is not None:
                    msgs = sync.add_msg(q.getName(), new_msg)
                    if msgs:
                        depth = msgs["depth"].getFrame()
                        color = msgs["colorize"].getCvFrame()
                        depth_vis = cv2.normalize(depth, None, 255, 0, cv2.NORM_INF, cv2.CV_8UC1)
                        depth_vis = cv2.equalizeHist(depth_vis)
                        depth_vis = cv2.applyColorMap(depth_vis, cv2.COLORMAP_HOT)
                        cv2.imshow("depth", depth_vis)
                        cv2.imshow("color", color)
                        rgb = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)
                        pcl = pcl_converter.rgbd_to_projection(depth, rgb)
                        pcl_converter.visualize_pcd()
                        # continue
                        # depth_vis = cv2.normalize(depth.getFrame(), None, 255, 0, cv2.NORM_INF, cv2.CV_8UC1)
                        # depth_vis = cv2.equalizeHist(depth_vis)
                        # depth_vis = cv2.applyColorMap(depth_vis, cv2.COLORMAP_HOT)
                        # cv2.imshow("depth", depth_vis)
                        
                        # xyz = _create_xyz(device, depth.getWidth(), depth.getHeight())
                        # exit()

                        # frame = depth.getFrame()
                        # frame = np.expand_dims(np.array(frame), axis=-1)
                        # pcl = (xyz * frame / 1000.0)  # To meters
                        # print("DTYPE: ", pcl.dtype)
                        # print("SIZE: ", pcl.shape)

                        rgb = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)

                        # pcl = pcl_converter.rgbd_to_projection(depth, rgb)
                        if len(pcl.points) > 0:
                            # open("pc.bin", "w").write("[\n"+",\n".join([str(b) for b in pcl.tobytes()]) + "]")
                            # rr.log_points("points", pcl.points, colors=pcl.colors)
                            msg_data = fb_create_rawimage(
                                {"sec": int(time.time_ns() // 1e9), "nsec": 1}, "rgb8", w, h, w * 3, rgb.reshape(-1))
                            if 0 in channel_to_subscription:
                                full_message = MessageDataHeader.pack(
                                    1, channel_to_subscription[0], time.time_ns()) + msg_data
                                foxglove_chanel.send(full_message)

                            # print("Simulated points: ", simulated_points)
                            msg_data = fb_create_pointcloud(
                                {"sec": int(time.time_ns() // 1e9), "nsec": 1}, np.asarray(pcl.points).reshape(-1))
                            if 1 in channel_to_subscription:
                                full_message_2 = MessageDataHeader.pack(
                                    1, channel_to_subscription[1], time.time_ns()) + msg_data
                                foxglove_chanel.send(full_message_2)
                            

            if cv2.waitKey(1) == "q":
                break


class Timestamp:
    sec: int
    nsec: int


def fb_create_pointcloud(timestamp: Timestamp, points: np.array, colors: np.array = None):
    D_SIZE = 8
    D_TYPE = 8  # Float64
    builder = flatbuffers.Builder(20000000)

    frame_id = builder.CreateString("front")

    x_string = builder.CreateString("x")
    y_string = builder.CreateString("y")
    z_string = builder.CreateString("z")

    PackedElementField.Start(builder)
    PackedElementField.AddName(builder, x_string)
    PackedElementField.AddOffset(builder, 0)
    PackedElementField.AddType(builder, D_TYPE)
    x_field = PackedElementField.End(builder)

    PackedElementField.Start(builder)
    PackedElementField.AddName(builder, y_string)
    PackedElementField.AddOffset(builder, D_SIZE)
    PackedElementField.AddType(builder, D_TYPE)
    y_field = PackedElementField.End(builder)

    PackedElementField.Start(builder)
    PackedElementField.AddName(builder, z_string)
    PackedElementField.AddOffset(builder, 2 * D_SIZE)
    PackedElementField.AddType(builder, D_TYPE)
    z_field = PackedElementField.End(builder)

    PointCloud.StartFieldsVector(builder, 3)
    builder.PrependUOffsetTRelative(x_field)
    builder.PrependUOffsetTRelative(y_field)
    builder.PrependUOffsetTRelative(z_field)
    fields = builder.EndVector()

    Vector3.Start(builder)
    Vector3.AddX(builder, 0)
    Vector3.AddY(builder, 0)
    Vector3.AddZ(builder, 0)
    position = Vector3.End(builder)

    Quaternion.Start(builder)
    Quaternion.AddX(builder, 0)
    Quaternion.AddY(builder, 0)
    Quaternion.AddZ(builder, 0)
    Quaternion.AddW(builder, 1)
    orientation = Quaternion.End(builder)

    Pose.Start(builder)
    Pose.AddPosition(builder, position)
    Pose.AddOrientation(builder, orientation)
    pose = Pose.End(builder)
    points_vector = builder.CreateByteVector(points.tobytes())
    timestamp = Time.CreateTime(builder, timestamp["sec"], 1)
    PointCloud.Start(builder)
    PointCloud.AddTimestamp(builder, timestamp)
    PointCloud.AddFrameId(builder, frame_id)
    PointCloud.AddPose(builder, pose)
    PointCloud.AddPointStride(builder, 3*D_SIZE)
    PointCloud.AddFields(builder, fields)
    PointCloud.AddData(builder, points_vector)
    pointcloud = PointCloud.End(builder)
    builder.Finish(pointcloud)
    pc = ClsPointCloud.GetRootAsPointCloud(builder.Output(), 0)
    return builder.Output()


def fb_create_rawimage(timestamp: Timestamp, encoding: str, width: int, height: int, step: int, image_data: np.array, frame_id="+x") -> bytearray:
    builder = flatbuffers.Builder(5000)
    data_vector = builder.CreateNumpyVector(image_data)
    bgr = builder.CreateString(encoding)
    frame_id = builder.CreateString("front")
    timestamp = Time.CreateTime(builder, timestamp["sec"], 1)

    RawImage.Start(builder)
    RawImage.AddTimestamp(builder, timestamp)
    RawImage.AddFrameId(builder, frame_id)
    RawImage.AddWidth(builder, width)
    RawImage.AddHeight(builder, height)
    RawImage.AddEncoding(builder, bgr)
    RawImage.AddStep(builder, width * 3)
    RawImage.AddData(builder, data_vector)
    img = RawImage.End(builder)
    builder.Finish(img)
    return builder.Output()


if __name__ == "__main__":
    run_cancellable(main())
