"use client";

import { useEffect, useState } from "react";
import { AuthProvider } from "react-oidc-context";
import { cognitoAuthConfig } from "@/lib/oidc";

/**
 * 認証コンテキストを全画面に供給する。
 *
 * oidc-client-ts は localStorage/window に触るので、SSR/プリレンダ時に AuthProvider を
 * 生成すると "window is not defined" で落ちる。→ マウント後（クライアント）だけ生成する。
 *
 * onSigninCallback: ログイン後に URL の ?code=... を消して綺麗にする。
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  return (
    <AuthProvider
      {...cognitoAuthConfig}
      onSigninCallback={() => {
        window.history.replaceState({}, document.title, window.location.pathname);
      }}
    >
      {children}
    </AuthProvider>
  );
}
