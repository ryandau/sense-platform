import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as rds from "aws-cdk-lib/aws-rds";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as triggers from "aws-cdk-lib/triggers";
import * as path from "path";
import { Construct } from "constructs";

export class SensePlatformStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const frontendDomain = this.node.tryGetContext("frontendDomain") || "localhost";

    // -----------------------------------------
    // VPC — private network for Lambda + RDS
    // -----------------------------------------
    const vpc = new ec2.Vpc(this, "SenseVpc", {
      vpcName: "sense-platform-vpc",
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: "isolated",
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
        {
          name: "public",
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
      ],
    });

    // -----------------------------------------
    // Security Groups
    // -----------------------------------------
    const lambdaSg = new ec2.SecurityGroup(this, "LambdaSg", {
      vpc,
      securityGroupName: "sense-platform-lambda",
      description: "sense-platform Lambda",
      allowAllOutbound: true,
    });

    const rdsSg = new ec2.SecurityGroup(this, "RdsSg", {
      vpc,
      securityGroupName: "sense-platform-rds",
      description: "sense-platform RDS",
      allowAllOutbound: false,
    });

    rdsSg.addIngressRule(
      lambdaSg,
      ec2.Port.tcp(5432),
      "Allow Lambda to connect to PostgreSQL"
    );

    // -----------------------------------------
    // VPC Endpoint — Secrets Manager
    // Lambdas in isolated subnets need this to
    // read secrets without internet access
    // -----------------------------------------
    vpc.addInterfaceEndpoint("SecretsManagerEndpoint", {
      service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
    });

    // -----------------------------------------
    // RDS — PostgreSQL with pgvector
    // Credentials auto-generated in Secrets Manager
    // RETAIN protects data if stack is deleted
    // -----------------------------------------
    const db = new rds.DatabaseInstance(this, "SenseDb", {
      instanceIdentifier: "sense-platform",
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_17,
      }),
      instanceType: ec2.InstanceType.of(
        ec2.InstanceClass.T4G,
        ec2.InstanceSize.MICRO
      ),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [rdsSg],
      databaseName: "sense",
      credentials: rds.Credentials.fromGeneratedSecret("sense_app"),
      allocatedStorage: 20,
      storageType: rds.StorageType.GP2,
      multiAz: false,
      publiclyAccessible: false,
      parameterGroup: new rds.ParameterGroup(this, "SenseDbParams", {
        engine: rds.DatabaseInstanceEngine.postgres({ version: rds.PostgresEngineVersion.VER_17 }),
        parameters: { "rds.force_ssl": "1" },
      }),
      backupRetention: cdk.Duration.days(1),
      deletionProtection: false,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      enablePerformanceInsights: false,
      autoMinorVersionUpgrade: true,
    });

    // -----------------------------------------
    // API Key — auto-generated in Secrets Manager
    // -----------------------------------------
    const apiKeySecret = new secretsmanager.Secret(this, "ApiKeySecret", {
      secretName: "sense-platform/api-key",
      generateSecretString: {
        excludePunctuation: true,
        passwordLength: 32,
      },
    });

    // -----------------------------------------
    // Schema Migration Lambda
    // Runs once on first deploy via Trigger
    // Applies schema and seeds device types
    // -----------------------------------------
    const migrationFn = new lambda.Function(this, "MigrationFunction", {
      functionName: "sense-platform-migration",
      description: "Applies database schema on first deploy",
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "index.handler",
      code: lambda.Code.fromAsset(
        path.join(__dirname, "../lambda/schema_migration"),
        {
          bundling: {
            image: lambda.Runtime.PYTHON_3_12.bundlingImage,
            command: [
              "bash", "-c",
              "pip install -r requirements.txt -t /asset-output && cp index.py /asset-output/",
            ],
          },
        }
      ),
      timeout: cdk.Duration.minutes(5),
      memorySize: 256,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [lambdaSg],
      environment: {
        DB_SECRET_ARN: db.secret!.secretArn,
        DEPLOY_TIME: new Date().toISOString(),
      },
    });

    db.secret!.grantRead(migrationFn);
    db.connections.allowFrom(migrationFn, ec2.Port.tcp(5432));

    new triggers.Trigger(this, "SchemaMigration", {
      handler: migrationFn,
      executeAfter: [db],
      executeOnHandlerChange: true,
    });

    // -----------------------------------------
    // Ingest Lambda
    // -----------------------------------------
    const ingestFn = new lambda.Function(this, "IngestFunction", {
      functionName: "sense-platform-ingest",
      description: "sense-platform ingest API — accepts readings from any device",
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "app.api.ingest.handler",
      code: lambda.Code.fromAsset(
        path.join(__dirname, "../../backend/package"),
        { exclude: ["*.pyc", "__pycache__"] }
      ),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [lambdaSg],
      environment: {
        DB_SECRET_ARN: db.secret!.secretArn,
        API_KEY_SECRET_ARN: apiKeySecret.secretArn,
        FRONTEND_DOMAIN: frontendDomain,
        FRONTEND_BUCKET_URL: `http://${frontendDomain}.s3-website-${this.region}.amazonaws.com`,
      },
    });

    db.secret!.grantRead(ingestFn);
    apiKeySecret.grantRead(ingestFn);
    db.connections.allowFrom(ingestFn, ec2.Port.tcp(5432));

    // -----------------------------------------
    // Bastion — SSM port forwarding to RDS
    // Stop when not in use: aws ec2 stop-instances --instance-ids <id>
    // Start when needed:    aws ec2 start-instances --instance-ids <id>
    // Stopped instance costs $0 (only ~$0.08/mo EBS)
    // -----------------------------------------
    const bastion = new ec2.BastionHostLinux(this, "Bastion", {
      vpc,
      subnetSelection: { subnetType: ec2.SubnetType.PUBLIC },
      instanceType: ec2.InstanceType.of(
        ec2.InstanceClass.T4G,
        ec2.InstanceSize.NANO
      ),
    });
    db.connections.allowFrom(bastion, ec2.Port.tcp(5432));

    // -----------------------------------------
    // API Gateway
    // -----------------------------------------
    const api = new apigateway.RestApi(this, "SenseApi", {
      restApiName: "sense-platform-api",
      description: "sense-platform public API",
      deployOptions: {
        stageName: "v1",
        loggingLevel: apigateway.MethodLoggingLevel.ERROR,
        dataTraceEnabled: false,
        metricsEnabled: true,
        throttlingRateLimit: 100,
        throttlingBurstLimit: 200,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: [
          `https://${frontendDomain}`,
          `http://${frontendDomain}`,
          `http://${frontendDomain}.s3-website-${this.region}.amazonaws.com`,
        ],
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: ["Content-Type", "X-API-Key"],
      },
    });

    const lambdaIntegration = new apigateway.LambdaIntegration(ingestFn, {
      requestTemplates: { "application/json": '{ "statusCode": "200" }' },
    });

    api.root.addMethod("ANY", lambdaIntegration);
    api.root.addProxy({
      defaultIntegration: lambdaIntegration,
      anyMethod: true,
    });

    // -----------------------------------------
    // Frontend — S3 static website
    // Cloudflare DNS points to this bucket
    // -----------------------------------------
    const frontendBucket = new s3.Bucket(this, "FrontendBucket", {
      bucketName: frontendDomain,
      websiteIndexDocument: "index.html",
      publicReadAccess: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ACLS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    new s3deploy.BucketDeployment(this, "FrontendDeployment", {
      sources: [s3deploy.Source.asset(path.join(__dirname, "../../frontend"))],
      destinationBucket: frontendBucket,
    });

    // -----------------------------------------
    // Outputs
    // -----------------------------------------
    new cdk.CfnOutput(this, "ApiUrl", {
      value: api.url,
      description: "API Gateway base URL",
      exportName: "SensePlatformApiUrl",
    });

    new cdk.CfnOutput(this, "IngestEndpoint", {
      value: `${api.url}ingest`,
      description: "POST sensor readings here",
    });

    new cdk.CfnOutput(this, "DbEndpoint", {
      value: db.instanceEndpoint.hostname,
      description: "RDS endpoint (private, VPC only)",
    });

    new cdk.CfnOutput(this, "DbSecretArn", {
      value: db.secret!.secretArn,
      description: "Secrets Manager ARN for DB credentials",
    });

    new cdk.CfnOutput(this, "ApiKeySecretArn", {
      value: apiKeySecret.secretArn,
      description: "Secrets Manager ARN for API key",
    });

    new cdk.CfnOutput(this, "BastionInstanceId", {
      value: bastion.instanceId,
      description: "SSM target for DB port forwarding",
    });

    new cdk.CfnOutput(this, "FrontendUrl", {
      value: frontendBucket.bucketWebsiteUrl,
      description: "S3 static website URL",
    });


    new cdk.CfnOutput(this, "LambdaFunctionName", {
      value: ingestFn.functionName,
      description: "Lambda function name",
      exportName: "SensePlatformLambdaName",
    });

    cdk.Tags.of(this).add("Project", "sense-platform");
    cdk.Tags.of(this).add("Owner", "ryan@donohue.ai");
    cdk.Tags.of(this).add("Environment", "production");
  }
}
