import json
from pathlib import Path
import builtins
import typing

from typing import Any

# import boto3
from aws_cdk import aws_ssm as ssm
from aws_cdk import core as cdk
from aws_cdk import pipelines
from aws_cdk.core import SecretValue

from environment import EKSMultiEnv
from eks.eks import EKSEnvironmentProps


class Pipeline(cdk.Stack):
    # pylint: disable=redefined-builtin
    # The 'id' parameter name is CDK convention.
    def __init__(self,
                 scope: cdk.Construct,
                 id: str,
                 pre_production_env: typing.Type[cdk.Environment],
                 production_env: typing.Type[cdk.Environment],
                 pipeline_repository_name: typing.Optional[builtins.str] = "eks-multi-environment-cdk-pipeline",
                 pipeline_repository_branch: typing.Optional[builtins.str] = "eks-multi-env",
                 **kwargs: Any) -> None:
        """Initialization for Pipeline stack.
        :param scope: scope of stack.
        :param id: id of stack.
        :param pre_production_env: cdk.Environment used for pre-production.
        :param production_env: cdk.Environment used for production.
        :param pipeline_repository_name: Repository name that will host the pipeline.Default: - "eks-multi-environment-cdk-pipeline".
        :param pipeline_repository_branch: .Default: Repository branch to sync the pipeline from - "eks-multi-env".
        """
        super().__init__(scope, id, **kwargs)

        self.pipeline_repository_name = pipeline_repository_name
        self.pipeline_repository_branch = pipeline_repository_branch
        self.pre_production_env = pre_production_env
        self.production_env = production_env

        github_input_source = pipelines.CodePipelineSource.git_hub(
            repo_string="{github_user}/{github_repo}".format(
                github_user=ssm.StringParameter.value_from_lookup(
                    self,
                    parameter_name='github-user',
                ),
                github_repo=self.pipeline_repository_name
            ),
            branch="main",
            authentication=SecretValue.secrets_manager('github-token'),
        )
        synth_action = pipelines.CodeBuildStep(
            "Synth",
            input=github_input_source,
            commands=[
                "pyenv local 3.7.10",
                "./scripts/install-deps.sh",
                "npm install -g aws-cdk",
                "cdk synth",
            ],
            primary_output_directory="cdk.out"
        )

        cdk_pipeline = pipelines.CodePipeline(
            self,
            "EKSMultiEnvPipeline",
            synth=synth_action,
            publish_assets_in_parallel=False,
            cli_version=Pipeline._get_cdk_cli_version(),
        )

        self._add_pre_prod_stage(cdk_pipeline)
        self._add_prod_stage(cdk_pipeline)

    @staticmethod
    def _get_cdk_cli_version() -> str:
        package_json_path = Path(__file__).resolve().parent.joinpath("package.json")
        with open(package_json_path) as package_json_file:
            package_json = json.load(package_json_file)
        cdk_cli_version = str(package_json["devDependencies"]["aws-cdk"])
        return cdk_cli_version

    def _add_pre_prod_stage(self, cdk_pipeline: pipelines.CodePipeline) -> None:
        eks_pre_production_props = EKSEnvironmentProps(
            env_name="pre-production",
            cluster_name="eks-multi-env",
            flux_config_repo_name=self.pipeline_repository_name,
            flux_config_branch_name=self.pipeline_repository_branch,
        )

        pre_production_stage = EKSMultiEnv(
            self,
            f"{EKSMultiEnv.__name__}-PreProduction",
            env=self.pre_production_env,
            eks_env_props=eks_pre_production_props
        )

        pre_production_stage = cdk_pipeline.add_stage(pre_production_stage)
        pre_production_stage.add_post(
            pipelines.ManualApprovalStep(
                "ConfirmPreProdDeploymentSuccessful",
                comment="Please approve deployment to production environment",
            )
        )

    def _add_prod_stage(self, cdk_pipeline: pipelines.CodePipeline) -> None:
        eks_production_props = EKSEnvironmentProps(
            env_name="production",
            cluster_name="eks-multi-env",
            flux_config_repo_name=self.pipeline_repository_name,
            flux_config_branch_name=self.pipeline_repository_branch,
        )
        production_stage = EKSMultiEnv(
            self,
            f"{EKSMultiEnv.__name__}-Production",
            env=self.production_env,
            eks_env_props=eks_production_props,
        )
        prod_stage = cdk_pipeline.add_stage(production_stage)
        _ = prod_stage
