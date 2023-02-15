const net = require("node:net");

const server = net.createServer((socket) => {
  socket.setNoDelay(true);
  socket.on("data", (data) => {
    // console.log("Got data");
  });
});

server.listen(5678, (s) => {
  console.log("server bound");
});
