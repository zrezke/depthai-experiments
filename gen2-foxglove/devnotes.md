@ 4k i had 15 fps, when just getting the frame from the queue.  

```py
is_success, im_buf_arr = cv2.imencode(".jpg", img)

# # read from .jpeg format to buffer of bytes
byte_im = im_buf_arr.tobytes()

# # data must be encoded in base64
data = base64.b64encode(byte_im).decode("ascii")
```
This above decresed my fps to 10.

Then when sending data via foxglove websocket i had 5 fps.
