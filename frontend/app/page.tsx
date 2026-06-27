"use client";

import { useState } from "react";
import { useAuth } from "react-oidc-context";
import { API_URL, COGNITO_DOMAIN, cognitoAuthConfig } from "@/lib/oidc";

type Trace = {
  route_mode: string;
  chosen_agent: string;
  total_ms: number;
  steps: { step: string; status: string; elapsed_ms: number; detail: string; error: string | null }[];
};

export default function Home() {
  const auth = useAuth();
  const [message, setMessage] = useState("東京のIT顧客を出して");
  const [routeMode, setRouteMode] = useState<"rule" | "llm">("rule");
  const [endpoint, setEndpoint] = useState<"/chat" | "/chain/lead-digest">("/chat");
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState("");
  const [trace, setTrace] = useState<Trace | null>(null);
  const [error, setError] = useState("");

  // --- 認証ローディング/エラー ---
  if (auth.isLoading) return <Center>認証情報を確認中…</Center>;
  if (auth.error) return <Center>認証エラー: {auth.error.message}</Center>;

  // --- 未ログイン: Cognito Hosted UI へ ---
  if (!auth.isAuthenticated) {
    return (
      <Center>
        <h1 style={{ fontSize: 22 }}>AIエージェント統合プラットフォーム</h1>
        <p style={{ opacity: 0.7 }}>営業支援マルチエージェント (mini)</p>
        <button style={btnPrimary} onClick={() => auth.signinRedirect()}>
          Cognito でログイン
        </button>
      </Center>
    );
  }

  // --- ログイン済み: API を叩く ---
  const idToken = auth.user?.id_token;

  async function send() {
    setLoading(true);
    setError("");
    setAnswer("");
    setTrace(null);
    try {
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${idToken}`, // ← Cognito の id_token（aud=client_id）
        },
        body: JSON.stringify({ message, route_mode: routeMode }),
      });
      if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
      const data = await res.json();
      setAnswer(data.output ?? "");
      setTrace(data.trace ?? null);
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }

  function logout() {
    // react-oidc-context のローカルセッション破棄 + Cognito Hosted UI のログアウト
    auth.removeUser();
    const redirect = encodeURIComponent(cognitoAuthConfig.redirect_uri);
    window.location.href =
      `https://${COGNITO_DOMAIN}/logout?client_id=${cognitoAuthConfig.client_id}&logout_uri=${redirect}`;
  }

  return (
    <div style={{ maxWidth: 760, margin: "0 auto", padding: 24 }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ fontSize: 20 }}>AIエージェント統合プラットフォーム</h1>
        <div style={{ fontSize: 13, opacity: 0.8 }}>
          {auth.user?.profile.email}{" "}
          <button style={btnGhost} onClick={logout}>
            ログアウト
          </button>
        </div>
      </header>

      <div style={card}>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={3}
          style={textarea}
          placeholder="例: 解約条件を教えて / 大阪の製造業の顧客を売上順で"
        />

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: "10px 0" }}>
          <label>
            ルーティング:&nbsp;
            <select value={routeMode} onChange={(e) => setRouteMode(e.target.value as any)} style={select}>
              <option value="rule">rule（ルールベース）</option>
              <option value="llm">llm（意図分類）</option>
            </select>
          </label>
          <label>
            エンドポイント:&nbsp;
            <select value={endpoint} onChange={(e) => setEndpoint(e.target.value as any)} style={select}>
              <option value="/chat">/chat（単一エージェント）</option>
              <option value="/chain/lead-digest">/chain（DataQuery→Summary）</option>
            </select>
          </label>
          <button style={btnPrimary} onClick={send} disabled={loading}>
            {loading ? "実行中…" : "送信"}
          </button>
        </div>
      </div>

      {error && <div style={{ ...card, color: "#fca5a5" }}>⚠ {error}</div>}

      {answer && (
        <div style={card}>
          <div style={label}>回答</div>
          <pre style={pre}>{answer}</pre>
        </div>
      )}

      {trace && (
        <div style={card}>
          <div style={label}>
            実行トレース（{trace.route_mode} / 選択: {trace.chosen_agent} / {trace.total_ms}ms）
          </div>
          {trace.steps.map((s, i) => (
            <div key={i} style={{ fontSize: 13, padding: "4px 0", borderBottom: "1px solid #1e293b" }}>
              <span style={{ color: s.status === "success" ? "#4ade80" : "#fca5a5" }}>●</span>{" "}
              <b>{s.step}</b> — {s.elapsed_ms}ms {s.error ? `(${s.error})` : ""}
              {s.detail && <div style={{ opacity: 0.7, marginLeft: 16 }}>{s.detail}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---- inline styles（Tailwind CDN は使わない＝プレビュー固まる問題回避） ---- */
const card: React.CSSProperties = {
  background: "#1e293b",
  borderRadius: 10,
  padding: 16,
  margin: "14px 0",
};
const label: React.CSSProperties = { fontSize: 12, opacity: 0.6, marginBottom: 6 };
const pre: React.CSSProperties = { whiteSpace: "pre-wrap", margin: 0, fontSize: 14, lineHeight: 1.6 };
const textarea: React.CSSProperties = {
  width: "100%",
  background: "#0f172a",
  color: "#e2e8f0",
  border: "1px solid #334155",
  borderRadius: 8,
  padding: 10,
  boxSizing: "border-box",
};
const select: React.CSSProperties = {
  background: "#0f172a",
  color: "#e2e8f0",
  border: "1px solid #334155",
  borderRadius: 6,
  padding: "4px 8px",
};
const btnPrimary: React.CSSProperties = {
  background: "#6366f1",
  color: "white",
  border: "none",
  borderRadius: 8,
  padding: "8px 18px",
  cursor: "pointer",
};
const btnGhost: React.CSSProperties = {
  background: "transparent",
  color: "#94a3b8",
  border: "1px solid #334155",
  borderRadius: 6,
  padding: "3px 10px",
  cursor: "pointer",
};

function Center({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        gap: 14,
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        padding: 24,
      }}
    >
      {children}
    </div>
  );
}
