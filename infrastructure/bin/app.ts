#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { SensePlatformStack } from "../lib/sense-platform-stack";

const app = new cdk.App();

new SensePlatformStack(app, "SensePlatformStack", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || "ap-southeast-2",
  },
  description: "sense.donohue.ai - Generic IoT sensor platform",
});
