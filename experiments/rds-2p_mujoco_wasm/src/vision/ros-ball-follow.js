/** rosbridge transport: the real ROS node owns camera inference and velocity control. */
export class RosBallFollow {
  constructor(onStatus, onDisconnect, onFrame = () => {}) {
    this.onStatus = onStatus;
    this.onDisconnect = onDisconnect;
    this.onFrame = onFrame;
    this.socket = null;
    this.status = null;
    this.heartbeat = null;
    this.lastStatusAt = -Infinity;
  }

  get connected() { return this.socket?.readyState === WebSocket.OPEN; }

  send(message) {
    if (this.connected) this.socket.send(JSON.stringify(message));
  }

  connect(address) {
    const url = new URL(address);
    if (!["ws:", "wss:"].includes(url.protocol)) throw new Error("Нужен адрес ws:// или wss://");
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      this.socket = socket;
      const timeout = setTimeout(() => { reject(new Error("Нет ответа от ROS-узла ball_follow")); this.close(); }, 8000);
      socket.onopen = () => {
        this.send({op:"advertise", topic:"/ball_follow/enable", type:"std_msgs/msg/Bool"});
        this.send({op:"subscribe", topic:"/ball_follow/status", type:"std_msgs/msg/String", throttle_rate:100});
        this.send({op:"subscribe", topic:"/ball_follow/image/compressed", type:"sensor_msgs/msg/CompressedImage", throttle_rate:200, queue_length:1});
      };
      socket.onmessage = event => {
        try {
          const message = JSON.parse(event.data);
          if (message.topic === "/ball_follow/image/compressed") {
            if (message.msg.format?.includes("jpeg") && typeof message.msg.data === "string" && message.msg.data.length < 2000000) {
              this.onFrame(`data:image/jpeg;base64,${message.msg.data}`);
            }
            return;
          }
          if (message.topic !== "/ball_follow/status") return;
          this.status = JSON.parse(message.msg.data);
          this.lastStatusAt = performance.now();
          if (this.status.ready) { clearTimeout(timeout); resolve(this); }
          this.onStatus(this.status);
        } catch { /* Ignore messages from unrelated rosbridge topics. */ }
      };
      socket.onerror = () => { clearTimeout(timeout); reject(new Error("Не удалось подключиться к rosbridge")); };
      socket.onclose = () => {
        clearTimeout(timeout);
        clearInterval(this.heartbeat);
        this.heartbeat = null;
        reject(new Error("Соединение ROS закрыто"));
        this.onDisconnect();
      };
    });
  }

  start() {
    if (!this.connected || performance.now()-this.lastStatusAt > 700) throw new Error("Нет свежего статуса ROS");
    if (this.status.manual_source) throw new Error(`Управление занято: ${this.status.manual_source}`);
    this.publishEnable(true);
    this.heartbeat = setInterval(() => {
      if (performance.now()-this.lastStatusAt > 700) {
        this.close(); return;
      }
      this.publishEnable(true);
    }, 200);
  }

  publishEnable(enabled) { this.send({op:"publish",topic:"/ball_follow/enable",msg:{data:enabled}}); }

  stop() {
    clearInterval(this.heartbeat);
    this.heartbeat = null;
    this.publishEnable(false);
  }

  close() {
    this.stop();
    this.send({op:"unsubscribe",topic:"/ball_follow/status"});
    this.send({op:"unsubscribe",topic:"/ball_follow/image/compressed"});
    this.socket?.close();
  }
}
