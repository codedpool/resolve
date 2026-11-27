/** A very small event emitter. `on` returns a function that removes the listener. */
export function createEmitter() {
  const listeners = new Map();

  return {
    on(name, listener) {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name).add(listener);
      return () => listeners.get(name)?.delete(listener);
    },
    emit(name, payload) {
      for (const listener of [...(listeners.get(name) || [])]) {
        try {
          listener(payload);
        } catch {
          // One broken listener must not stop audio or the other listeners.
        }
      }
    },
    clear() {
      listeners.clear();
    },
  };
}
