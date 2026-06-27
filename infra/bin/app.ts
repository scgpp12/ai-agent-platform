#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { PlatformStack } from "../lib/platform-stack";

const app = new cdk.App();

// フロントの本番オリジン（Vercel）。初回は不明なので localhost のまま deploy し、
// Vercel の URL が分かったら `cdk deploy -c frontendOrigin=https://xxx.vercel.app` で再デプロイ。
const frontendOrigin =
  app.node.tryGetContext("frontendOrigin") || "http://localhost:3000";

new PlatformStack(app, "AiAgentPlatform", {
  frontendOrigin,
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.AWS_REGION || process.env.CDK_DEFAULT_REGION || "ap-northeast-1",
  },
  description: "AIエージェント統合プラットフォーム (mini) — Lambda+DynamoDB+Bedrock+Cognito",
});
