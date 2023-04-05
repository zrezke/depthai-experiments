import flatbuffers
from foxglove_schemas_flatbuffer.RawImage import RawImage as ClsRawImage
from foxglove_schemas_flatbuffer.PointCloud import PointCloud as ClsPointCloud
import foxglove_schemas_flatbuffer.Time as Time
from foxglove_schemas_flatbuffer import get_schema
import foxglove_schemas_flatbuffer.RawImage as RawImage
import foxglove_schemas_flatbuffer.PointCloud as PointCloud
import foxglove_schemas_flatbuffer.Pose as Pose
from foxglove_schemas_flatbuffer import Vector3, Quaternion, PackedElementField
import numpy as np


class Timestamp:
    sec: int
    nsec: int

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


def fb_create_pointcloud(timestamp: Timestamp, points: np.array, colors: np.array = None):
    D_SIZE = 8
    D_TYPE = 8
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
