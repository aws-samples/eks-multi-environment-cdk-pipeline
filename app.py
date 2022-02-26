#!/usr/bin/env python3
import os

from monocdk_nag import AwsSolutionsChecks
# For consistency with TypeScript code, `cdk` is the preferred import name for
# the CDK's core module.  The following line also imports it as `core` for use
# with examples from the CDK Developer's Guide, which are in the process of
# being updated to use `cdk`.  You may delete this import if you don't need it.
from aws_cdk import core
from aws_cdk import core as cdk

from environment import EKSEnvironmentProps
from environment import EKSMultiEnv
from pipeline import Pipeline

dev_env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"],
    region=os.environ["CDK_DEFAULT_REGION"]
)

pipeline_env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"],
    region=os.environ["CDK_DEFAULT_REGION"]
)
pre_production_env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"],
    region=os.environ["CDK_DEFAULT_REGION"]
)
production_env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"],
    region=os.environ["CDK_DEFAULT_REGION"]
)

app = core.App()


eks_dev_props = EKSEnvironmentProps(
    env_name="dev",
    cluster_name="eks",
    flux_config_repo_name="flux-eks-gitops-config",
    flux_config_branch_name="eks-multi-env",
)

EKSMultiEnv(app,
            "EKSEnvDev",
            eks_env_props=eks_dev_props,
            env=dev_env,
            )

Pipeline(app,
         f"{EKSMultiEnv.__name__}",
         env=pipeline_env,
         pre_production_env=pre_production_env,
         production_env=production_env,
         )
core.Aspects.of(app).add(AwsSolutionsChecks())

app.synth()
