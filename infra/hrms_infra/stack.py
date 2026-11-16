"""Everything for one environment:

  VPC (public + private subnets)
  RDS PostgreSQL 16 (private, encrypted, password in Secrets Manager)
  S3 bucket for employee documents (KMS encrypted, private)
  Cognito user pool + app client + one group per role
  ECS Fargate API behind an Application Load Balancer (image built from ../backend)
  S3 + CloudFront for the React app; CloudFront sends /api/* to the load balancer
"""
from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    aws_cloudfront as cf,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_kms as kms,
    aws_logs as logs,
    aws_rds as rds,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_secretsmanager as sm,
)
from constructs import Construct

ROOT = Path(__file__).resolve().parents[2]
ROLES = {
    "master_admin": "Master admin", "hr": "HR", "payroll_preparer": "Payroll preparer",
    "finance_approver": "Finance approver", "hod": "Head of department", "employee": "Employee",
}


class HrmsStack(cdk.Stack):
    def __init__(self, scope: Construct, cid: str, *, env_name: str, cfg: dict, **kw) -> None:
        super().__init__(scope, cid, **kw)
        retain = bool(cfg.get("retain"))
        removal = cdk.RemovalPolicy.RETAIN if retain else cdk.RemovalPolicy.DESTROY

        # ---------------------------------------------------------------- network
        vpc = ec2.Vpc(self, "Vpc", max_azs=2, nat_gateways=int(cfg.get("natGateways", 1)),
                      subnet_configuration=[
                          ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                          ec2.SubnetConfiguration(name="app", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=24),
                          ec2.SubnetConfiguration(name="data", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24),
                      ])

        key = kms.Key(self, "DataKey", enable_key_rotation=True, alias=f"alias/peak-hrms-{env_name}", removal_policy=removal)

        # ---------------------------------------------------------------- database
        db_sg = ec2.SecurityGroup(self, "DbSg", vpc=vpc, description="Postgres: API only")
        db = rds.DatabaseInstance(
            self, "Db",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16),
            instance_type=ec2.InstanceType(cfg.get("dbInstance", "t4g.micro")),
            vpc=vpc, vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[db_sg],
            database_name="hrms",
            credentials=rds.Credentials.from_generated_secret("hrms", secret_name=f"peak-hrms/{env_name}/db"),
            allocated_storage=20, max_allocated_storage=100,
            storage_encrypted=True, storage_encryption_key=key,
            multi_az=retain,
            backup_retention=cdk.Duration.days(14 if retain else 1),
            deletion_protection=retain,
            removal_policy=cdk.RemovalPolicy.SNAPSHOT if retain else cdk.RemovalPolicy.DESTROY,
        )

        # ---------------------------------------------------------------- files
        files = s3.Bucket(
            self, "Files", encryption=s3.BucketEncryption.KMS, encryption_key=key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True, versioned=retain,
            removal_policy=removal, auto_delete_objects=not retain,
        )

        # ---------------------------------------------------------------- sign-in (Cognito)
        pool = cognito.UserPool(
            self, "Users", user_pool_name=f"peak-hrms-{env_name}",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True, username=True),
            password_policy=cognito.PasswordPolicy(min_length=8, require_lowercase=True, require_uppercase=True, require_digits=True,
                                                   require_symbols=False, temp_password_validity=cdk.Duration.days(7)),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=removal,
        )
        client = pool.add_client("Web", auth_flows=cognito.AuthFlow(user_password=True), generate_secret=False,
                                 access_token_validity=cdk.Duration.hours(8), prevent_user_existence_errors=True)
        for name, desc in ROLES.items():
            cognito.CfnUserPoolGroup(self, f"Group{name.title().replace('_', '')}", user_pool_id=pool.user_pool_id, group_name=name, description=desc)

        # ---------------------------------------------------------------- app secrets
        app_secret = sm.Secret(self, "AppSecret", secret_name=f"peak-hrms/{env_name}/app",
                               generate_secret_string=sm.SecretStringGenerator(
                                   secret_string_template='{"note":"jwt_secret and field_key are generated"}',
                                   generate_string_key="jwt_secret", exclude_punctuation=True, password_length=48),
                               removal_policy=removal)
        field_key = sm.Secret(self, "FieldKey", secret_name=f"peak-hrms/{env_name}/field-key",
                              description="Encrypts PAN and bank account numbers. Never rotate without re-encrypting.",
                              generate_secret_string=sm.SecretStringGenerator(exclude_punctuation=True, password_length=64),
                              removal_policy=cdk.RemovalPolicy.RETAIN if retain else cdk.RemovalPolicy.DESTROY)

        # ---------------------------------------------------------------- API on ECS Fargate
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights=retain)
        api = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "Api", cluster=cluster,
            cpu=int(cfg.get("apiCpu", 512)), memory_limit_mib=int(cfg.get("apiMemory", 1024)),
            desired_count=int(cfg.get("apiCount", 1)),
            public_load_balancer=True,
            open_listener=False,  # only CloudFront may reach it (see below)
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            enable_execute_command=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            health_check_grace_period=cdk.Duration.seconds(300),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(str(ROOT / "backend")),
                container_name="api", container_port=8000,
                log_driver=ecs.LogDrivers.aws_logs(stream_prefix="api", log_retention=logs.RetentionDays.ONE_MONTH),
                environment={
                    "ENVIRONMENT": env_name,
                    "AUTH_MODE": "cognito",
                    "COGNITO_REGION": self.region,
                    "COGNITO_USER_POOL_ID": pool.user_pool_id,
                    "COGNITO_CLIENT_ID": client.user_pool_client_id,
                    "DB_HOST": db.db_instance_endpoint_address,
                    "DB_PORT": db.db_instance_endpoint_port,
                    "DB_NAME": "hrms",
                    "S3_BUCKET": files.bucket_name,
                    "BIOMETRIC_ADAPTER": "excel",
                    "SEED_DEMO": "true" if cfg.get("seedDemo") else "false",
                },
                secrets={
                    "DB_USERNAME": ecs.Secret.from_secrets_manager(db.secret, "username"),
                    "DB_PASSWORD": ecs.Secret.from_secrets_manager(db.secret, "password"),
                    "JWT_SECRET": ecs.Secret.from_secrets_manager(app_secret, "jwt_secret"),
                    "FIELD_ENCRYPTION_KEY": ecs.Secret.from_secrets_manager(field_key),
                },
            ),
        )
        api.target_group.configure_health_check(path="/api/health", healthy_http_codes="200", interval=cdk.Duration.seconds(20))
        api.load_balancer.set_attribute("idle_timeout.timeout_seconds", "300")
        db.connections.allow_default_port_from(api.service, "API to Postgres")
        files.grant_read_write(api.task_definition.task_role)
        key.grant_encrypt_decrypt(api.task_definition.task_role)
        api.task_definition.task_role.add_to_principal_policy(iam.PolicyStatement(
            actions=["cognito-idp:AdminCreateUser", "cognito-idp:AdminGetUser", "cognito-idp:AdminAddUserToGroup", "cognito-idp:AdminRemoveUserFromGroup",
                     "cognito-idp:AdminListGroupsForUser", "cognito-idp:AdminDisableUser", "cognito-idp:AdminEnableUser", "cognito-idp:AdminSetUserPassword"],
            resources=[pool.user_pool_arn]))
        scaling = api.service.auto_scale_task_count(min_capacity=int(cfg.get("apiCount", 1)), max_capacity=max(2, int(cfg.get("apiCount", 1)) * 2))
        scaling.scale_on_cpu_utilization("Cpu", target_utilization_percent=65)

        # ---------------------------------------------------------------- web (S3 + CloudFront)
        web = s3.Bucket(self, "Web", block_public_access=s3.BlockPublicAccess.BLOCK_ALL, enforce_ssl=True,
                        removal_policy=cdk.RemovalPolicy.DESTROY, auto_delete_objects=True)
        api_origin = origins.LoadBalancerV2Origin(api.load_balancer, protocol_policy=cf.OriginProtocolPolicy.HTTP_ONLY,
                                                  read_timeout=cdk.Duration.seconds(60))
        api_behavior = cf.BehaviorOptions(origin=api_origin, viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                                          allowed_methods=cf.AllowedMethods.ALLOW_ALL, cache_policy=cf.CachePolicy.CACHING_DISABLED,
                                          origin_request_policy=cf.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER)
        # Single-page app: paths without a file extension get index.html (only on the web behaviour, never on /api)
        spa = cf.Function(self, "SpaRewrite", code=cf.FunctionCode.from_inline(
            "function handler(event){var r=event.request;if(r.uri.indexOf('.')===-1){r.uri='/index.html';}return r;}"),
            runtime=cf.FunctionRuntime.JS_2_0)
        dist = cf.Distribution(
            self, "Cdn",
            comment=f"Peak HRMS {env_name}",
            default_root_object="index.html",
            default_behavior=cf.BehaviorOptions(origin=origins.S3BucketOrigin.with_origin_access_control(web),
                                                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                                                function_associations=[cf.FunctionAssociation(function=spa, event_type=cf.FunctionEventType.VIEWER_REQUEST)]),
            additional_behaviors={"/api/*": api_behavior, "/docs": api_behavior, "/openapi.json": api_behavior},
            price_class=cf.PriceClass.PRICE_CLASS_200,
        )
        dist_dir = ROOT / "frontend" / "dist"
        if dist_dir.exists():
            s3deploy.BucketDeployment(self, "WebDeploy", sources=[s3deploy.Source.asset(str(dist_dir))], destination_bucket=web,
                                      distribution=dist, distribution_paths=["/*"])
        else:
            cdk.Annotations.of(self).add_warning("frontend/dist not found: run `npm run build` in frontend before deploy to publish the web app.")

        # Only CloudFront should reach the load balancer
        api.load_balancer.connections.allow_from(ec2.Peer.prefix_list(_cloudfront_prefix_list(self)), ec2.Port.tcp(80), "CloudFront")

        # ---------------------------------------------------------------- outputs
        cdk.CfnOutput(self, "AppUrl", value=f"https://{dist.distribution_domain_name}")
        cdk.CfnOutput(self, "ApiDocs", value=f"https://{dist.distribution_domain_name}/docs")
        cdk.CfnOutput(self, "UserPoolId", value=pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=client.user_pool_client_id)
        cdk.CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        cdk.CfnOutput(self, "ServiceName", value=api.service.service_name)
        cdk.CfnOutput(self, "FilesBucket", value=files.bucket_name)


def _cloudfront_prefix_list(scope: Construct) -> str:
    """AWS-managed prefix list of CloudFront origin-facing addresses, looked up at deploy time."""
    from aws_cdk import custom_resources as cr

    lookup = cr.AwsCustomResource(
        scope, "CfPrefixList",
        on_update=cr.AwsSdkCall(service="EC2", action="describeManagedPrefixLists",
                                parameters={"Filters": [{"Name": "prefix-list-name", "Values": ["com.amazonaws.global.cloudfront.origin-facing"]}]},
                                physical_resource_id=cr.PhysicalResourceId.of("cloudfront-origin-facing"),
                                output_paths=["PrefixLists.0.PrefixListId"]),
        policy=cr.AwsCustomResourcePolicy.from_sdk_calls(resources=cr.AwsCustomResourcePolicy.ANY_RESOURCE),
    )
    return lookup.get_response_field("PrefixLists.0.PrefixListId")
