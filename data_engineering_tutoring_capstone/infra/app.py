"""Optional AWS CDK stack for the capstone.

`cdk synth` is a local, no-deployment exercise. `cdk deploy` creates billable
cloud resources and should only be run after checking account eligibility,
budgets, region, and cleanup instructions.
"""

from pathlib import Path

from aws_cdk import (
    App,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_glue as glue,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_s3_notifications as notifications,
)
from constructs import Construct


class CommerceDataPlatformStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        lake = s3.Bucket(
            self,
            "DataLake",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        handler = lambda_.Function(
            self,
            "BronzeObjectHandler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(Path(__file__).parent / "lambda")),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={"BRONZE_BUCKET": lake.bucket_name},
        )
        lake.grant_read(handler)
        lake.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            notifications.LambdaDestination(handler),
            s3.NotificationKeyFilter(prefix="bronze/"),
        )

        glue.CfnDatabase(
            self,
            "AnalyticsCatalog",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name="commerce_analytics",
                description="Catalog namespace for the tutoring capstone",
            ),
        )

        CfnOutput(self, "DataLakeBucketName", value=lake.bucket_name)


app = App()
CommerceDataPlatformStack(app, "CommerceDataPlatformStack")
app.synth()

