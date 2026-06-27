/**
 * Cognito を OIDC プロバイダとして使う設定。
 *
 * authority に Cognito の issuer(ユーザープールURL)を渡すと、
 * react-oidc-context が discovery(.well-known)経由で Hosted UI のエンドポイントを自動取得する。
 * ＝ログイン画面は Cognito Hosted UI（こちらでUIを作らない）。
 *
 * 値は Vercel の環境変数(NEXT_PUBLIC_*)から注入する（CDK Outputs を貼る）。
 */
export const cognitoAuthConfig = {
  authority: process.env.NEXT_PUBLIC_COGNITO_AUTHORITY as string,
  client_id: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID as string,
  redirect_uri: process.env.NEXT_PUBLIC_REDIRECT_URI as string,
  response_type: "code", // Authorization Code + PKCE
  scope: "openid email profile",
};

export const API_URL = process.env.NEXT_PUBLIC_API_URL as string;

// Hosted UI のログアウト用ドメイン（例: aiagent-xxxx.auth.ap-northeast-1.amazoncognito.com）
export const COGNITO_DOMAIN = process.env.NEXT_PUBLIC_COGNITO_DOMAIN as string;
