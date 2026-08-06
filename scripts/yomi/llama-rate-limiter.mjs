// Rate limiter and circuit breaker for Llama API calls

class RateLimiter {
  constructor(maxConcurrent = 2, queueTimeout = 30000) {
    this.maxConcurrent = maxConcurrent;
    this.queueTimeout = queueTimeout;
    this.running = 0;
    this.queue = [];
  }

  async run(fn) {
    if (this.running >= this.maxConcurrent) {
      console.log(`Rate limit reached: ${this.running}/${this.maxConcurrent} running, queuing request`);
      await this.waitForSlot();
    }

    this.running++;
    try {
      return await fn();
    } finally {
      this.running--;
      this.processQueue();
    }
  }

  async waitForSlot() {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        const index = this.queue.indexOf({ resolve, reject });
        if (index > -1) this.queue.splice(index, 1);
        reject(new Error('Rate limiter queue timeout'));
      }, this.queueTimeout);

      this.queue.push({ resolve, reject, timeout });
    });
  }

  processQueue() {
    if (this.queue.length > 0 && this.running < this.maxConcurrent) {
      const { resolve, reject, timeout } = this.queue.shift();
      clearTimeout(timeout);
      resolve();
    }
  }

  getStats() {
    return {
      running: this.running,
      queued: this.queue.length,
      maxConcurrent: this.maxConcurrent
    };
  }
}

class CircuitBreaker {
  constructor(threshold = 5, timeout = 60000) {
    this.threshold = threshold;
    this.timeout = timeout;
    this.failureCount = 0;
    this.lastFailureTime = null;
    this.state = 'closed'; // closed, open, half-open
  }

  async run(fn) {
    if (this.state === 'open') {
      if (Date.now() - this.lastFailureTime > this.timeout) {
        console.log('Circuit breaker entering half-open state');
        this.state = 'half-open';
      } else {
        throw new Error('Circuit breaker is open');
      }
    }

    try {
      const result = await fn();
      this.onSuccess();
      return result;
    } catch (error) {
      this.onFailure();
      throw error;
    }
  }

  onSuccess() {
    this.failureCount = 0;
    if (this.state === 'half-open') {
      console.log('Circuit breaker closing after successful request');
      this.state = 'closed';
    }
  }

  onFailure() {
    this.failureCount++;
    this.lastFailureTime = Date.now();
    
    if (this.failureCount >= this.threshold) {
      console.log(`Circuit breaker opening after ${this.failureCount} failures`);
      this.state = 'open';
    }
  }

  getState() {
    return {
      state: this.state,
      failureCount: this.failureCount,
      lastFailureTime: this.lastFailureTime
    };
  }

  reset() {
    this.failureCount = 0;
    this.lastFailureTime = null;
    this.state = 'closed';
    console.log('Circuit breaker reset');
  }
}

// Create singleton instances
const summaryRateLimiter = new RateLimiter(1, 120000); // Conservative: 1 concurrent for summaries, 2min queue timeout
const dailyRateLimiter = new RateLimiter(1, 180000); // Conservative: 1 concurrent for daily summaries, 3min queue timeout (reduced from 3 for GPU optimization)
const summaryCircuitBreaker = new CircuitBreaker(2, 180000); // Open after 2 failures, 3min timeout
const dailyCircuitBreaker = new CircuitBreaker(5, 240000); // More tolerant: Open after 5 failures, 4min timeout

export {
  RateLimiter,
  CircuitBreaker,
  summaryRateLimiter,
  dailyRateLimiter,
  summaryCircuitBreaker,
  dailyCircuitBreaker
};