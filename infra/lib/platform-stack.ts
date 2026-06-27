/**
 * PlatformStack — プラットフォーム一式を 1 スタックで定義
 * =====================================================
 *
 * 構成（CLAUDE.md の方針: TS は初学者向けにシンプルに）:
 *   - DynamoDB ×2（Customers + GSI / Knowledge）
 *   - Lambda（FastAPI+Mangum, Python3.12, Docker不要の事前ビルド asset）
 *   - API Gateway HTTP API + Cognito JWT Authorizer + CORS
 *   - Cognito User Pool + Client + Hosted UI ドメイン
 *
 * IAM は最小権限（Bedrock は haiku 推論プロファイル + Titan、DynamoDB は当該2表のみ）。
 */
import * as path from "path";
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as iam from "aws-cdk-lib/aws-iam";
import * as cognito from "aws-cdk-lib/aws-cognito";
import {
  HttpApi,
  HttpMethod,
  CorsHttpMethod,
} from "aws-cdk-lib/aws-apigatewayv2";
import { HttpLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import { HttpJwtAuthorizer } from "aws-cdk-lib/aws-apigatewayv2-authorizers";

export interface PlatformStackProps extends cdk.StackProps {
  /** フロント本番オリジン（CORS / Cognito コールバックに使う） */
  frontendOrigin: string;
}

export class PlatformStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: PlatformStackProps) {
    super(scope, id, props);

    const region = cdk.Stack.of(this).region;
    const account = cdk.Stack.of(this).account;

    // 後片付けしやすいよう全リソースにタグ（CLAUDE.md: 統一タグで掃除しやすく）
    cdk.Tags.of(this).add("project", "ai-agent-platform");

    // ------------------------------------------------------------------ //
    // 1) DynamoDB
    // ------------------------------------------------------------------ //
    // 顧客テーブル。PK=id。地域別検索＋売上ソート用に GSI(region, monthly_revenue)。
    const customersTable = new dynamodb.Table(this, "CustomersTable", {
      partitionKey: { name: "id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST, // 按需計費（CLAUDE.md 既定）
      removalPolicy: cdk.RemovalPolicy.DESTROY, // 練習用: destroy で消す
    });
    customersTable.addGlobalSecondaryIndex({
      indexName: "region-index",
      partitionKey: { name: "region", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "monthly_revenue", type: dynamodb.AttributeType.NUMBER },
    });

    // 知識(FAQ)テーブル。PK=id。text と（seed時に計算した）vector を保持。
    const knowledgeTable = new dynamodb.Table(this, "KnowledgeTable", {
      partitionKey: { name: "id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ------------------------------------------------------------------ //
    // 2) Cognito（トークン発行側＝認証担当の責務をここで用意）
    // ------------------------------------------------------------------ //
    const userPool = new cognito.UserPool(this, "UserPool", {
      selfSignUpEnabled: true, // 練習用に自己サインアップ可
      signInAliases: { email: true },
      autoVerify: { email: true },
      passwordPolicy: { minLength: 8, requireDigits: true, requireLowercase: true },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // SPA(Vercel) 用パブリッククライアント（シークレット無し、Authorization Code + PKCE）
    const userPoolClient = userPool.addClient("WebClient", {
      generateSecret: false,
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: [`${props.frontendOrigin}/`, "http://localhost:3000/"],
        logoutUrls: [`${props.frontendOrigin}/`, "http://localhost:3000/"],
      },
      supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
    });

    // Hosted UI ドメイン。プレフィックスに 'cognito' を含めない（CLAUDE.md の落とし穴）。
    const userPoolDomain = userPool.addDomain("HostedUiDomain", {
      cognitoDomain: { domainPrefix: `aiagent-${account}` },
    });

    // ------------------------------------------------------------------ //
    // 3) Lambda（既存 FastAPI を Mangum でラップした build/ を取り込む）
    // ------------------------------------------------------------------ //
    const fn = new lambda.Function(this, "ApiFunction", {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "handler.handler",
      // 事前ビルド済みディレクトリ（scripts/build_lambda.sh で作る。Docker 不要）
      code: lambda.Code.fromAsset(path.join(__dirname, "..", "..", "backend", "build")),
      timeout: cdk.Duration.seconds(30), // API GW HTTP API の上限に合わせる
      memorySize: 512,
      environment: {
        // backend スイッチを本番構成に
        LLM_BACKEND: "bedrock",
        EMBED_BACKEND: "bedrock",
        DATA_BACKEND: "dynamo",
        AUTH_BACKEND: "cognito",
        BEDROCK_MODEL_ID: "jp.anthropic.claude-haiku-4-5-20251001-v1:0",
        BEDROCK_EMBED_MODEL: "amazon.titan-embed-text-v2:0",
        CUSTOMERS_TABLE: customersTable.tableName,
        KNOWLEDGE_TABLE: knowledgeTable.tableName,
        COGNITO_REGION: region,
        COGNITO_USER_POOL_ID: userPool.userPoolId,
        COGNITO_APP_CLIENT_ID: userPoolClient.userPoolClientId,
        // CORS は API GW 側で付けるので Lambda(FastAPI)側は無効化（二重付与回避）
        CORS_ALLOW_ORIGINS: "",
      },
    });

    // IAM: DynamoDB は当該2表のみ読み書き（最小権限）
    customersTable.grantReadWriteData(fn);
    knowledgeTable.grantReadWriteData(fn);

    // IAM: Bedrock InvokeModel（foundation-model + inference-profile 両方が要る）
    fn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel"],
        resources: [
          // Claude haiku の基盤モデル（推論プロファイルが各地域へルーティングするので region は *）
          `arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`,
          // 地域推論プロファイル本体
          `arn:aws:bedrock:${region}:${account}:inference-profile/jp.anthropic.claude-haiku-4-5-20251001-v1:0`,
          // Titan 埋め込み（通常モデル）
          `arn:aws:bedrock:${region}::foundation-model/amazon.titan-embed-text-v2:0`,
        ],
      })
    );

    // ------------------------------------------------------------------ //
    // 4) API Gateway HTTP API + Cognito JWT Authorizer + CORS
    // ------------------------------------------------------------------ //
    const integration = new HttpLambdaIntegration("LambdaIntegration", fn);

    // Cognito の id_token を検証する Authorizer（issuer=ユーザープール, audience=client）
    const authorizer = new HttpJwtAuthorizer(
      "CognitoAuthorizer",
      `https://cognito-idp.${region}.amazonaws.com/${userPool.userPoolId}`,
      { jwtAudience: [userPoolClient.userPoolClientId] }
    );

    const httpApi = new HttpApi(this, "HttpApi", {
      // CORS はゲートウェイで一括処理（プリフライト OPTIONS は authorizer を通さない）
      corsPreflight: {
        allowOrigins: [props.frontendOrigin, "http://localhost:3000"],
        allowMethods: [CorsHttpMethod.GET, CorsHttpMethod.POST, CorsHttpMethod.OPTIONS],
        allowHeaders: ["authorization", "content-type"],
      },
    });

    // /health は認証なしで疎通確認できるように（より具体的なルートが優先される）
    httpApi.addRoutes({
      path: "/health",
      methods: [HttpMethod.GET],
      integration,
    });

    // それ以外は全て Cognito 認証必須
    httpApi.addRoutes({
      path: "/{proxy+}",
      methods: [HttpMethod.GET, HttpMethod.POST],
      integration,
      authorizer,
    });

    // ------------------------------------------------------------------ //
    // 5) Outputs（フロントの env / seed スクリプトで使う）
    // ------------------------------------------------------------------ //
    new cdk.CfnOutput(this, "ApiUrl", { value: httpApi.apiEndpoint });
    new cdk.CfnOutput(this, "UserPoolId", { value: userPool.userPoolId });
    new cdk.CfnOutput(this, "AppClientId", { value: userPoolClient.userPoolClientId });
    new cdk.CfnOutput(this, "CognitoIssuer", {
      value: `https://cognito-idp.${region}.amazonaws.com/${userPool.userPoolId}`,
    });
    new cdk.CfnOutput(this, "HostedUiDomain", {
      value: `${userPoolDomain.domainName}.auth.${region}.amazoncognito.com`,
    });
    new cdk.CfnOutput(this, "CustomersTableName", { value: customersTable.tableName });
    new cdk.CfnOutput(this, "KnowledgeTableName", { value: knowledgeTable.tableName });
    new cdk.CfnOutput(this, "Region", { value: region });
  }
}
