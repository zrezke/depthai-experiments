import zmq
import json
from struct import Struct
MessageDataHeader = Struct("<BIQ")

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
