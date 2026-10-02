import { token } from "../api.js";

export function subscribeEvents(onEvent) {
  let socket = null;
  let timer = null;
  let closed = false;

  function connect() {
    if (closed || socket || !window.WebSocket || !token()) return;
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${scheme}//${location.host}/ws/events`);
    socket.onopen = () => socket.send(JSON.stringify({ token: token() }));
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message && message.type && message.type !== "ping") onEvent(message);
      } catch (_) {}
    };
    socket.onclose = () => {
      socket = null;
      clearTimeout(timer);
      if (!closed) timer = setTimeout(connect, 10000);
    };
  }

  connect();
  return () => {
    closed = true;
    clearTimeout(timer);
    if (socket) socket.close();
  };
}
