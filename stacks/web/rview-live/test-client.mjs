import { WebSocket } from "ws";

const ws = new WebSocket("ws://localhost:3002/ws");

ws.on("open", () => {
  console.log("client connected");
  // send text to trigger rview_show
  setTimeout(() => {
    ws.send(JSON.stringify({ type: "text", text: "Show the image https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cat03.jpg/1200px-Cat03.jpg in view default" }));
    console.log("sent text");
  }, 3000);
});

ws.on("message", (data) => {
  const msg = JSON.parse(data.toString("utf8"));
  console.log("<--", JSON.stringify(msg, null, 2));
});

ws.on("error", (err) => console.error("WS error:", err.message));
ws.on("close", () => console.log("client closed"));

setTimeout(() => {
  console.log("closing test client");
  ws.close();
  process.exit(0);
}, 15000);
