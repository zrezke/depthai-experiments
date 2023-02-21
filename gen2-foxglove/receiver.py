import socket
import struct

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("localhost", 9999))
    s.listen()
    conn, addr = s.accept()
    with conn:
        print(f"Connected by {addr}")

        buf = bytes()
        i = 0
        while True:
            msg_len = conn.recv(4)
            msg_len = struct.unpack(">I", msg_len)[0]
            while len(buf) < msg_len:
                data = conn.recv(msg_len)
                buf += data
                i += len(data)
            print("Received (MB): ",  len(buf) / 1e6)
            buf = bytes()
            i = 0

            if not data:
                break
            #print(f"rcvd:", len(data))
            # conn.sendall(data)
