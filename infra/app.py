#!/usr/bin/env python3
"""Peak HRMS on AWS. One stack per environment.

    cdk deploy  -c env=dev      # or qa / prod
    cdk destroy -c env=dev

Build the web app first (frontend/dist is uploaded):  cd ../frontend && npm run build
"""
import os

import aws_cdk as cdk

from hrms_infra.stack import HrmsStack

app = cdk.App()
env_name = app.node.try_get_context("env") or "dev"
envs = app.node.try_get_context("envs")
if env_name not in envs:
    raise SystemExit(f"Unknown env '{env_name}'. Use one of: {', '.join(envs)}")
cfg = envs[env_name]

HrmsStack(
    app,
    f"PeakHrms-{env_name}",
    env_name=env_name,
    cfg=cfg,
    env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=cfg["region"]),
    description=f"Peak HRMS ({env_name}): VPC, Postgres, Cognito, ECS Fargate API, S3 + CloudFront web",
)
cdk.Tags.of(app).add("project", "peak-hrms")
cdk.Tags.of(app).add("env", env_name)
app.synth()
