class LowLatencyAudioProcessor {
    constructor(sampleRate = 16000) {
        this.sampleRate = sampleRate;
        this.audioContext = null;
        this.playerNode = null;
        this.captureNode = null;
        this.playQueue = [];
        this.isCapturing = false;
        this.bufferSize = 256;
        this.prewarmThreshold = sampleRate * 0.01;
    }

    async init() {
        this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
            sampleRate: this.sampleRate,
            latencyHint: 'interactive'
        });

        await this.audioContext.audioWorklet.addModule(
            URL.createObjectURL(new Blob([this._getPlayerWorklet()], { type: 'application/javascript' }))
        );
        await this.audioContext.audioWorklet.addModule(
            URL.createObjectURL(new Blob([this._getCaptureWorklet()], { type: 'application/javascript' }))
        );

        this.playerNode = new AudioWorkletNode(this.audioContext, 'pcm-player', {
            processorOptions: { prewarmThreshold: this.prewarmThreshold },
            numberOfInputs: 0,
            numberOfOutputs: 1,
            outputChannelCount: [1]
        });
        this.playerNode.connect(this.audioContext.destination);

        this.playerNode.port.onmessage = (e) => {
            if (e.data.type === 'underrun') {
                console.warn('音频欠载!');
            }
        };

        this.captureNode = new AudioWorkletNode(this.audioContext, 'pcm-capture', {
            processorOptions: { targetSampleRate: this.sampleRate, bufferSize: this.bufferSize }
        });

        return this;
    }

    _getPlayerWorklet() {
        return `
            class PCMPlayer extends AudioWorkletProcessor {
                constructor(options) {
                    super();
                    this.queue = [];
                    this.offset = 0;
                    this.buffered = 0;
                    this.started = false;
                    this.prewarmThreshold = options.processorOptions?.prewarmThreshold || 160;
                    this.totalSamples = 0;
                    this.lastReportTime = 0;
                }

                process(inputs, outputs) {
                    const output = outputs[0][0];
                    
                    if (!this.started) {
                        if (this.buffered < this.prewarmThreshold) {
                            output.fill(0);
                            return true;
                        }
                        this.started = true;
                        this.port.postMessage({ type: 'started' });
                    }

                    for (let i = 0; i < output.length; i++) {
                        if (!this.queue.length) {
                            this.started = false;
                            output.fill(0);
                            this.port.postMessage({ type: 'underrun' });
                            return true;
                        }
                        const current = this.queue[0];
                        output[i] = current[this.offset++];
                        this.buffered--;
                        this.totalSamples++;
                        if (this.offset >= current.length) {
                            this.queue.shift();
                            this.offset = 0;
                        }
                    }
                    
                    const now = currentTime;
                    if (now - this.lastReportTime > 1) {
                        this.port.postMessage({ 
                            type: 'stats', 
                            buffered: this.buffered,
                            queueDepth: this.queue.length 
                        });
                        this.lastReportTime = now;
                    }
                    return true;
                }
            }
            registerProcessor('pcm-player', PCMPlayer);
        `;
    }

    _getCaptureWorklet() {
        return `
            class PCMCapture extends AudioWorkletProcessor {
                constructor(options) {
                    super();
                    this.capturing = false;
                    this.targetRate = options.processorOptions?.targetSampleRate || 16000;
                    this.bufferSize = options.processorOptions?.bufferSize || 512;
                    this.ringBuffer = new Int16Array(this.bufferSize * 4);
                    this.writeIdx = 0;
                    this.readIdx = 0;
                    this.written = 0;

                    this.port.onmessage = (e) => {
                        if (e.data.type === 'start') this.capturing = true;
                        if (e.data.type === 'stop') this.capturing = false;
                    };
                }

                process(inputs) {
                    if (!this.capturing || !inputs[0].length) return true;

                    const input = inputs[0][0];
                    const ratio = sampleRate / this.targetRate;
                    const outLen = Math.floor(input.length / ratio);

                    for (let i = 0; i < outLen; i++) {
                        const srcIdx = Math.floor(i * ratio);
                        this.ringBuffer[this.writeIdx] = Math.max(-32768, Math.min(32767, input[srcIdx] * 32767));
                        this.writeIdx = (this.writeIdx + 1) % this.ringBuffer.length;
                        this.written++;
                    }

                    if (this.written >= this.bufferSize) {
                        const buffer = new ArrayBuffer(this.written * 2 + 1);
                        const view = new DataView(buffer);
                        view.setUint8(0, 0x51);
                        
                        let bufIdx = 0;
                        while (this.written > 0) {
                            view.setInt16(bufIdx * 2 + 1, this.ringBuffer[this.readIdx], true);
                            this.readIdx = (this.readIdx + 1) % this.ringBuffer.length;
                            bufIdx++;
                            this.written--;
                        }
                        
                        this.port.postMessage({ type: 'audio', buffer });
                    }
                    return true;
                }
            }
            registerProcessor('pcm-capture', PCMCapture);
        `;
    }

    playAudio(pcmData) {
        const samples = pcmData.length / 2;
        const floatData = new Float32Array(samples);
        
        const view = new DataView(pcmData.buffer || pcmData);
        for (let i = 0; i < samples; i++) {
            floatData[i] = view.getInt16(i * 2, true) / 32768;
        }

        if (this.playerNode) {
            this.playerNode.port.postMessage(floatData);
        }
    }

    async startCapture(onData) {
        if (this.isCapturing) return;

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: this.sampleRate,
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl: false
                }
            });

            const source = this.audioContext.createMediaStreamSource(stream);
            source.connect(this.captureNode);

            this.captureNode.port.onmessage = (e) => {
                if (e.data.type === 'audio') {
                    onData(new Uint8Array(e.data.buffer));
                }
            };

            this.captureNode.port.postMessage({ type: 'start' });
            this.isCapturing = true;
            this._stream = stream;

        } catch (err) {
            console.error('启动麦克风失败:', err);
            throw err;
        }
    }

    stopCapture() {
        if (!this.isCapturing) return;

        this.captureNode.port.postMessage({ type: 'stop' });
        if (this._stream) {
            this._stream.getTracks().forEach(t => t.stop());
        }
        this.isCapturing = false;
    }

    getLatency() {
        if (this.audioContext) {
            const baseLatency = this.audioContext.baseLatency || 0.01;
            const outputLatency = this.audioContext.outputLatency || 0;
            return {
                baseMs: baseLatency * 1000,
                outputMs: outputLatency * 1000,
                totalMs: (baseLatency + outputLatency) * 1000
            };
        }
        return { baseMs: 0, outputMs: 0, totalMs: 0 };
    }

    resume() {
        if (this.audioContext && this.audioContext.state === 'suspended') {
            return this.audioContext.resume();
        }
    }
}

window.LowLatencyAudioProcessor = LowLatencyAudioProcessor;
