import type { Metadata } from "next";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "AIエージェント統合プラットフォーム",
  description: "複数AIエージェントのオーケストレーション (mini)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body
        style={{
          fontFamily: "system-ui, sans-serif",
          margin: 0,
          background: "#0f172a",
          color: "#e2e8f0",
        }}
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
