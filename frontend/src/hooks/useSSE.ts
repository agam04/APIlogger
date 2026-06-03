import { useEffect, useRef } from "react";

export interface SSEEvent {
  type: string;
  service_id?: string;
  status?: string;
}

export function useSSE(onEvent: (e: SSEEvent) => void): void {
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;

    let es: EventSource;
    let retryTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      es = new EventSource(`/api/v1/events`);

      es.onmessage = (e) => {
        try {
          const parsed: SSEEvent = JSON.parse(e.data);
          cbRef.current(parsed);
        } catch {
          // ignore malformed events
        }
      };

      es.onerror = () => {
        es.close();
        // Reconnect after 3 s with exponential backoff (simple linear here)
        retryTimeout = setTimeout(connect, 3_000);
      };
    }

    connect();

    return () => {
      clearTimeout(retryTimeout);
      es?.close();
    };
  }, []);
}
