/** Fake browser audio and socket pieces for the voice tests. */

export function fakeAudioContext() {
  const context = {
    currentTime: 0,
    state: "running",
    destination: { name: "destination" },
    sources: [],
    buffers: [],
    createGain() {
      return { gain: { value: 1 }, connect() {}, disconnect() {} };
    },
    createBuffer(channels, length, sampleRate) {
      const buffer = {
        length,
        sampleRate,
        duration: length / sampleRate,
        data: new Float32Array(length),
        getChannelData() {
          return this.data;
        },
      };
      context.buffers.push(buffer);
      return buffer;
    },
    createBufferSource() {
      const source = {
        buffer: null,
        startedAt: null,
        stopped: false,
        onended: null,
        connect() {},
        disconnect() {},
        start(when) {
          this.startedAt = when;
        },
        stop() {
          this.stopped = true;
        },
      };
      context.sources.push(source);
      return source;
    },
    async close() {
      context.state = "closed";
    },
  };
  return context;
}

export function pcmBytes(samples) {
  const view = new DataView(new ArrayBuffer(samples.length * 2));
  samples.forEach((value, index) => view.setInt16(index * 2, value, true));
  return view.buffer;
}

export class FakeSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this.closedWith = null;
    FakeSocket.instances.push(this);
  }

  send(data) {
    this.sent.push(data);
  }

  close(code) {
    this.closedWith = code ?? 1000;
    this.readyState = 3;
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  receive(data) {
    this.onmessage?.({ data: typeof data === "object" && !(data instanceof ArrayBuffer) ? JSON.stringify(data) : data });
  }

  drop(code = 1006) {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  get json() {
    return this.sent.filter((item) => typeof item === "string").map((item) => JSON.parse(item));
  }

  get binary() {
    return this.sent.filter((item) => typeof item !== "string");
  }
}
