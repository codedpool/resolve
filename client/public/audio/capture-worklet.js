/* global AudioWorkletProcessor, registerProcessor, sampleRate */
/* Microphone capture worklet. It runs on the audio thread, so it only gathers the raw samples into
   chunks of about 20 ms and hands them to the page. Resampling to 16 kHz and framing happen on the
   page (src/lib/audio/resampler.js), where they can be tested. Plain JavaScript on purpose: this
   file is served as it is. */

class CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const ms = (options && options.processorOptions && options.processorOptions.chunkMs) || 20;
    this.size = Math.max(128, Math.round((sampleRate * ms) / 1000));
    this.buffer = new Float32Array(this.size);
    this.filled = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0];
    // Several channels are averaged into one. Most microphones are mono already.
    const mix = input.length > 1 ? new Float32Array(channel.length) : channel;
    if (input.length > 1) {
      for (let c = 0; c < input.length; c += 1) {
        for (let i = 0; i < channel.length; i += 1) mix[i] += input[c][i] / input.length;
      }
    }

    let offset = 0;
    while (offset < mix.length) {
      const take = Math.min(this.size - this.filled, mix.length - offset);
      this.buffer.set(mix.subarray(offset, offset + take), this.filled);
      this.filled += take;
      offset += take;
      if (this.filled === this.size) {
        const copy = this.buffer.slice();
        this.port.postMessage({ samples: copy, sampleRate }, [copy.buffer]);
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("capture-processor", CaptureProcessor);
