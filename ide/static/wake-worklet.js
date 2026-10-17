// «Oye EDITH»: pasa el audio del micrófono al hilo principal en bloques de 40 ms (a 16 kHz).
// Corre en el hilo de audio: no se detiene aunque la ventana esté oculta en la bandeja.
class EdithMic extends AudioWorkletProcessor {
  constructor() {
    super();
    this.size = Math.round(sampleRate * 0.04);
    this.buf = new Float32Array(this.size);
    this.n = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        this.buf[this.n++] = ch[i];
        if (this.n === this.size) {
          this.port.postMessage(this.buf.slice(0));
          this.n = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("edith-mic", EdithMic);
