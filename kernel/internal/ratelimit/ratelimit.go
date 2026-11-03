// Package ratelimit is a small in-memory, per-IP, fixed-window rate
// limiter -- no Redis, no external dependency, the same "boring and
// small" posture as the rest of the kernel (ARCHITECTURE.md's "what we
// explicitly did not build"). This is enough to blunt casual brute-force
// and scraping against a single kernel process.
//
// Limitation worth knowing before scaling past one instance: counters
// live in this process's memory, so running more than one kernel
// replica behind a load balancer gives each replica its own independent
// quota (effectively multiplying the real limit by replica count).
// Swap this for a shared store (Redis, or a Postgres table) if that
// ever matters -- nothing else about the Middleware call sites would
// need to change.
package ratelimit

import (
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

type Limiter struct {
	mu       sync.Mutex
	window   time.Duration
	max      int
	counters map[string]*counter
}

type counter struct {
	count     int
	windowEnd time.Time
}

// New starts a limiter allowing `max` requests per `window` per key. A
// background goroutine periodically drops expired counters so memory
// doesn't grow unbounded over a long-running process.
func New(max int, window time.Duration) *Limiter {
	l := &Limiter{window: window, max: max, counters: make(map[string]*counter)}
	go l.cleanupLoop()
	return l
}

func (l *Limiter) cleanupLoop() {
	for {
		time.Sleep(l.window)
		now := time.Now()
		l.mu.Lock()
		for k, c := range l.counters {
			if now.After(c.windowEnd) {
				delete(l.counters, k)
			}
		}
		l.mu.Unlock()
	}
}

// Allow reports whether `key` may proceed under the current window's
// quota, incrementing its counter either way.
func (l *Limiter) Allow(key string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()

	now := time.Now()
	c, ok := l.counters[key]
	if !ok || now.After(c.windowEnd) {
		l.counters[key] = &counter{count: 1, windowEnd: now.Add(l.window)}
		return true
	}
	if c.count >= l.max {
		return false
	}
	c.count++
	return true
}

// Middleware wraps a handler, rejecting with 429 once the calling IP
// exceeds this limiter's quota. `name` namespaces the key so a tight
// auth-only limiter and a loose general-purpose one never share counts
// for the same client IP.
func (l *Limiter) Middleware(name string, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !l.Allow(name + ":" + clientIP(r)) {
			w.Header().Set("Retry-After", "60")
			http.Error(w, `{"error":"too many requests -- slow down and try again shortly"}`, http.StatusTooManyRequests)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// clientIP never trusts X-Forwarded-For unless TRUST_PROXY_HEADERS=true
// is explicitly set -- a header any client can set to an arbitrary
// value would otherwise make this entire limiter trivially bypassable
// by just sending a different fake IP on every request. Only set that
// env var when the kernel is genuinely behind a reverse proxy/load
// balancer that overwrites this header with the real client address
// rather than passing through whatever the client sent.
func clientIP(r *http.Request) string {
	if os.Getenv("TRUST_PROXY_HEADERS") == "true" {
		if fwd := r.Header.Get("X-Forwarded-For"); fwd != "" {
			if i := strings.IndexByte(fwd, ','); i >= 0 {
				return strings.TrimSpace(fwd[:i])
			}
			return strings.TrimSpace(fwd)
		}
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}
