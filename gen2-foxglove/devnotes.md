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

## Update 16.2.2023
### 1080p@60fps
- Flatbuffer via WS: 54fps in studio
  - doesn't require base64 + faster deserialization in studio
  - colorImage messages range from ~50-60 messages per second so there is some bottleneck somewhere inside studio code that struggles to keep up with the speed of new messages (couldn't figure it out yet) 
- JSON via WS: 45fps in studio

### 4k@30fps
- sucks for both
  - studio just completely gives up for 4k, drops to about 10fps when using flatbuffers and about 8fps when using json (should be 30fps) 
