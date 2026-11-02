"use client";

import { useEffect, useRef, useState } from "react";

type Message = {
  role: "user" | "ai";
  content: string;
  toolsUsed?: string[];
};

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [model, setModel] = useState<string>("");
  const sessionId = useRef<string>("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    sessionId.current = crypto.randomUUID();
    fetch("/api/health")
      .then((r) => r.json())
      .then((d) => setModel(d.data.llm_model))
      .catch(() => setModel("backend 연결 실패"));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setLoading(true);

    // 스트리밍 중인 AI 말풍선 상태
    let started = false;
    let acc = "";
    let tools: string[] = [];
    const patchLast = () =>
      setMessages((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { role: "ai", content: acc, toolsUsed: tools };
        return copy;
      });
    const ensureBubble = () => {
      if (!started) {
        started = true;
        setMessages((prev) => [...prev, { role: "ai", content: "" }]);
      }
    };

    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId.current, message: text }),
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const evt = JSON.parse(line.slice(5));
          if (evt.type === "token") {
            ensureBubble();
            acc += evt.content;
            patchLast();
          } else if (evt.type === "tool") {
            ensureBubble();
            tools = [...tools, evt.name];
            patchLast();
          } else if (evt.type === "error") {
            throw new Error(evt.message);
          }
        }
      }
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "ai", content: `오류가 발생했습니다: ${String(e)}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="chat-shell">
      <header className="chat-header">
        <h1>LLM Wrapper Chat</h1>
        <span className="model">model: {model || "..."}</span>
      </header>

      <section className="chat-messages">
        {messages.length === 0 && (
          <p className="empty-hint">
            멀티턴 대화를 지원하는 LangGraph tool-calling 데모입니다.
            <br />
            예: &ldquo;지금 몇 시야?&rdquo;, &ldquo;123 * 45 계산해줘&rdquo;
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ display: "contents" }}>
            <div className={`bubble ${m.role}`}>{m.content}</div>
            {m.toolsUsed && m.toolsUsed.length > 0 && (
              <span className="tools-note">🔧 사용된 도구: {m.toolsUsed.join(", ")}</span>
            )}
          </div>
        ))}
        {loading && messages[messages.length - 1]?.role === "user" && (
          <div className="bubble ai">생각 중…</div>
        )}
        <div ref={bottomRef} />
      </section>

      <footer className="chat-input">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) send();
          }}
          placeholder="메시지를 입력하세요"
          disabled={loading}
        />
        <button onClick={send} disabled={loading || !input.trim()}>
          전송
        </button>
      </footer>
    </main>
  );
}
