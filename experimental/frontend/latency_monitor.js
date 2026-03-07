class LatencyMonitor {
    constructor() {
        this.samples = [];
        this.maxSamples = 100;
        this.sentPings = {};
    }

    sendPing(ws) {
        const id = Date.now() + Math.random();
        this.sentPings[id] = performance.now();
        ws.send(JSON.stringify({ type: 'ping', id }));
    }

    recordPong(id) {
        const sentTime = this.sentPings[id];
        if (sentTime) {
            const rtt = performance.now() - sentTime;
            this.samples.push(rtt);
            if (this.samples.length > this.maxSamples) {
                this.samples.shift();
            }
            delete this.sentPings[id];
            return rtt;
        }
        return null;
    }

    getStats() {
        if (this.samples.length === 0) return null;
        
        const sorted = [...this.samples].sort((a, b) => a - b);
        const sum = this.samples.reduce((a, b) => a + b, 0);
        
        return {
            min: sorted[0].toFixed(1),
            max: sorted[sorted.length - 1].toFixed(1),
            avg: (sum / this.samples.length).toFixed(1),
            p50: sorted[Math.floor(sorted.length * 0.5)].toFixed(1),
            p95: sorted[Math.floor(sorted.length * 0.95)].toFixed(1),
            count: this.samples.length
        };
    }
}

class AudioLatencyEstimator {
    constructor() {
        this.timestamps = [];
    }

    markReceive() {
        this.timestamps.push({
            receiveTime: performance.now(),
            playTime: null
        });
    }

    markPlay() {
        for (let i = 0; i < this.timestamps.length; i++) {
            if (!this.timestamps[i].playTime) {
                this.timestamps[i].playTime = performance.now();
                break;
            }
        }
        
        if (this.timestamps.length > 50) {
            this.timestamps.shift();
        }
    }

    getEstimate() {
        const validSamples = this.timestamps.filter(t => t.playTime);
        if (validSamples.length === 0) return null;
        
        const delays = validSamples.map(t => t.playTime - t.receiveTime);
        const avg = delays.reduce((a, b) => a + b, 0) / delays.length;
        
        return {
            avgMs: avg.toFixed(1),
            samples: validSamples.length
        };
    }
}

class JitterBuffer {
    constructor(targetDelayMs = 30, sampleRate = 16000) {
        this.targetDelay = targetDelayMs / 1000;
        this.sampleRate = sampleRate;
        this.buffer = [];
        this.maxBuffer = sampleRate * 0.3;
    }

    push(audioData) {
        this.buffer.push({
            data: audioData,
            time: performance.now()
        });

        while (this.getBufferLength() > this.maxBuffer) {
            this.buffer.shift();
        }
    }

    pull() {
        if (this.buffer.length === 0) return null;

        const currentDelay = this.getBufferLength() / this.sampleRate;
        
        if (currentDelay > this.targetDelay * 1.5) {
            while (this.buffer.length > 1 && 
                   this.getBufferLength() > this.targetDelay * 1.2) {
                this.buffer.shift();
            }
        }

        return this.buffer.shift();
    }

    getBufferLength() {
        return this.buffer.reduce((sum, item) => sum + (item.data.length / 2), 0);
    }

    getDelayMs() {
        return (this.getBufferLength() / this.sampleRate) * 1000;
    }
}

window.LatencyMonitor = LatencyMonitor;
window.AudioLatencyEstimator = AudioLatencyEstimator;
window.JitterBuffer = JitterBuffer;
